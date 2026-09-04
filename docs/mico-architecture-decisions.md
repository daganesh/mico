# `mico` — Architecture Decision Log

Companion to PRD v3.0.0. Records design decisions taken during pre-HLD architecture review.
Status values: **Decided**, **Provisional** (may change during HLD), **Open**.

---

## AD-01 — Async core, sync CLI wrapper

**Status:** Decided

The core service layer is async. The CLI drives it via `asyncio.run()`; FastAPI calls it natively.

**Rationale:** Not concurrency volume — a single user generates almost none. The driver is that agent invocations are long (minutes) and must not block the interface. Multiple tasks must be able to run in parallel and be handled properly. A sync core would force the web layer into threadpool workarounds for exactly the operations that matter most.

**Cost accepted:** `brain/` carries async signatures despite SQLite being effectively synchronous.

**Rejected:** sync core with threadpool offload; sync core with an async-only streaming path.

---

## AD-02 — Concurrency model: optimistic, per-track, at commit only

**Status:** Decided

**Problem identified:** the hazard is not file contention but **lost updates**. Long Run A reads revision 47; short Run B reads 47 and commits 48; A then commits a brief authored against 47, silently erasing B. Because briefs are wholesale overwrite with no merge semantics, last-write-wins means last-write-destroys.

The synchronisation point is therefore the **base revision**, not the file.

**Model:**

- **Non-mutating operations** (`recap`, `delta`, `evidence`, `ask`, `task`, `artifact`) — unlimited parallelism, no coordination.
- **Mutating operations** (`refresh`, `condense`, committing `chat`) — run fully in parallel; only the commit is serialised per track.
- Each Run records `base_revision` at start.
- At commit, under a short-held per-track lock: if `track.current_revision != run.base_revision` → conflict.

Lock is held for milliseconds, not for Run duration. A 6-minute refresh never blocks a 20-second one.

**Conflict resolution:**

| Mode | Behaviour |
|---|---|
| `autonomous` | **A — reject and re-run** against the new base, bounded retries to prevent livelock |
| `proposal` | **B — reject and surface** both versions to the user |

**Rejected — C (agent-mediated rebase):** feeding the agent the new base plus its own proposal to reconcile. Non-deterministic, and makes conflict resolution a correctness-critical prompt.

**Rejected — D (no parallel mutating tasks):** a serial per-track queue. Simpler and eliminates the conflict path entirely, but a long scheduled refresh would block a manual one behind it — the exact UI blocking AD-01 exists to avoid. Optimistic concurrency pays a rare re-run instead of a common wait. Recorded as a close call.

**Scheduled vs. manual:** a scheduled mutating Run is **skipped with a logged reason** if a manual mutating Run is already in flight on that track. It would likely lose the conflict and burn tokens; the next fire picks it up.

### Consequent PRD changes

- **§3.3 rejection of a second Run on a locked track is removed.** Replaced by: unlimited concurrent reads, concurrent mutating Runs permitted, commit serialised with optimistic check.
- **Sidecar renamed `.proposed.<run_id>.md`.** Per-track alone collides under concurrent mutating Runs. Side benefit: the filename identifies the owning Run, improving orphan recovery.
- New Run fields: `base_revision`, `retry_of`.

---

## AD-03 — Commit atomicity

**Status:** Provisional

An accepted Mutation writes `brief.md`, a compressed revision file, a SQLite Revision row, evidence index rows, a Track timestamp, sidecar deletion, and optionally a git commit. This is not atomic.

**Approach:** SQLite transaction wraps the file write; the brief is written to a temp name and `os.replace()`d (atomic on POSIX and Windows) inside the transaction. The failure window shrinks to microseconds and §3.2 reconciliation covers the remainder. Git commit happens after, outside the transaction, best-effort — it is explicitly not load-bearing (§9.3).

**To confirm during HLD:** whether a journal file for true two-phase commit is warranted.

---

## AD-04 — Storage interface: narrow port

**Status:** Decided

The v1/v2 claim that swapping the storage engine requires zero changes elsewhere was **dishonest**, because storage is hybrid by *requirement*: briefs must be Markdown files since human editability and git-diffability are product requirements, not implementation details.

**Two ABCs:**

- `BriefStore` — filesystem, effectively fixed. Not meaningfully swappable.
- `MetadataStore` — SQLite. Genuinely swappable, via the narrow port below.

### Narrow port, not a wide interface

A single `MetadataStore` ABC, but **only generic low-level I/O is abstract**. All entity-specific logic lives once in a concrete layer expressed in terms of those primitives.

**Abstract — implemented per backend (~12):**

```
Records:      insert · get · update · delete · upsert
Queries:      query(spec) · count(spec) · exists(spec)
Transaction:  begin · commit · rollback
Schema:       migrate · current_version
Search:       search(text, scope)          # optional, see below
```

**Concrete — written once, shared by all backends:** `get_active_tracks`, `latest_revision`, `revisions_since`, `dead_pointers_for_track`, `parked_runs`, `open_ledger_entries`, `unresolved_notifications`, and the rest. Roughly 60 call sites collapse to 12 abstract methods plus one shared implementation.

Implementing a new backend is then small enough to be largely mechanical.

**Rejected — per-aggregate repositories** (`TrackRepository`, `RevisionRepository`, …): cleaner in isolation but multiplies the substitution surface sixfold for no benefit at this scale.

### The query spec is the load-bearing piece

`query(spec)` carries the whole abstraction; its expressiveness determines whether the port succeeds or leaks.

A declarative spec object: field/operator/value predicates with AND/OR, plus order, limit, offset. Operators bounded to a closed set — `eq`, `ne`, `lt`, `gt`, `in`, `contains`, `is_null`. **Backends translate the spec; they never receive SQL.**

Too weak and the concrete layer fetches broadly and filters in Python. Too rich and it becomes an ORM. At this system's scale (below) the spec can stay deliberately simple — in-Python filtering is acceptable outside the dashboard-listing and search paths.

### `search` is optional

FTS5 is SQLite-specific with no equivalent in a flat-file backend. It stays in the port but backends advertise `supports_search`; the concrete layer falls back to a naive scan when absent. An explicitly degraded path is better than pretending every backend offers full-text.

### Transactions serve the unit-of-work need

A context manager over `begin` / `commit` / `rollback`, usable from the concrete layer. AD-03's atomic commit spans Revision, Evidence, and Track writes, so a transaction boundary is required regardless — this provides it without a separate `UnitOfWork` class. **Closes the open question raised under AD-03.**

### Scale context

**Dozens of tracks per user, not hundreds** — human capacity is the bottleneck. May reach many dozens, but most are idle or archived at any time. At weekly refresh cadence across ~40 active tracks, revisions total a few thousand rows over years.

Everything fits in memory. This is why the query spec need not be sophisticated, and why the concrete layer may filter in Python where convenient.

**PRD §14 amendment:** the stated targets (200 active tracks, 20k evidence pointers, 50k revisions) were inserted speculatively during the v2 rewrite and overstate real usage. Revise to ~50 active tracks, ~100 total including archived, low thousands of revisions.

### Honest note on SQLAlchemy Core

SQLAlchemy Core is this abstraction, already written and already backend-portable. Building bespoke primitives duplicates it.

The dependency-free version is defensible here specifically because the scale removes SQLAlchemy's main advantages — query sophistication and dialect portability. Recorded as a **deliberate choice**, not an oversight.

### M1 acceptance criterion, amended

The real value of this abstraction is **testability** — running the full pipeline against in-memory fakes — not vendor substitution; nobody will swap SQLite for Postgres in a single-user local tool. M1 should therefore prove "the pipeline runs green against an in-memory `MetadataStore`" rather than "swap the backend."

---

## AD-05 — No persistent agent process

**Status:** Decided

Each turn is a fresh `claude -p --resume <session_id>`. There is no long-lived agent process to own — only a session ID in `mico` state and one in-flight subprocess per turn.

**Consequences:** no process pool, no supervisor, no PTY. The web layer needs a per-Run stream buffer so a browser reconnect can catch up; nothing more. "Interactive chat window" must not be read as implying a persistent terminal session.

---

## AD-06 — Service layer shape

**Status:** Provisional

A facade object with explicit command and result dataclasses, called identically by CLI and web.

**Rationale:** the web layer needs serialisable results regardless; returning domain objects directly into Pydantic response models is where layering violations typically appear.

---

## AD-07 — Task budgets and timeouts

**Status:** Decided

**Timeout is per-stage, not per-task.** "Task timed out" is unactionable when a task has phases with wildly different profiles: agent invocation is minutes and agent-dominated; Stage 1 is milliseconds; Stage 2 is seconds; commit is milliseconds. A Stage 1 hang is a `mico` bug — raising a timeout cannot fix it.

- **User-facing:** an overall task budget, adjustable. In practice this governs the agent phase, the only one where waiting longer is a real answer.
- **Internal:** per-stage limits are engineering constants, not user-facing.

**On timeout:**

1. **Kill and reap the subprocess.** An orphaned `claude -p` still holds the user's third-party credentials and can still write files — worse than a hang. Timeout and user-cancel share this code path.
2. **Retain the partial sidecar**, mark the Run `timed_out`, surface as inspectable. **Do not validate it** — a half-written brief fails Stage 1 in confusing ways.
3. Offer **two distinct actions**: *extend* (raise the budget, subprocess keeps running, no work lost) and *abandon* (kill now). Extend is preferred over kill-and-restart-with-a-bigger-number.

**Extend is not a retry** — same Run, same subprocess, raised budget. This distinction must be explicit in the Run state machine.

---

## AD-08 — Configurable run attributes

**Status:** Decided

Implemented as a generic **`run_config` object**, not a timeout field. Model selection, max retries, and `--allowedTools` overrides will want the same resolution chain; retrofitting it later is worse than building it once.

**Four-level resolution:**

```
global default → per-operation default → per-track override → per-run override
```

- **Per-operation** is the natural home for defaults: `refresh` may traverse a dozen sources while `condense` reads one brief.
- **Per-track** prevents one heavyweight track forcing a global raise.
- **Per-run** is the disposable case (`--timeout 20m`), never persisted.

The timeout dialog offers *extend once* or *extend and save as the new default for this track/operation* — the moment the user learns the right value is the right moment to offer persistence.

**The effective resolved config is recorded on the Run.** Without it, a task that timed out under a since-changed setting is undebuggable.

---

## AD-09 — Error handling: recovery-class scheme

**Status:** Decided

Failures are classified by **what makes them go away**, not by where they occurred. The class determines the affordance, so no UI surface special-cases individual error types.

### Six classes

| Class | Meaning | Automatic response | User affordance |
|---|---|---|---|
| **Transient** | Likely succeeds unchanged | Retry with backoff | Retry now |
| **Depleted** | Allowance exhausted; resolves without user action | Suspend + periodic re-probe | Wait, top up, or switch provider |
| **Budget** | Ran out of a `mico`-controlled allowance | None | Extend, or abandon |
| **Config** | Environment is wrong | None | Fix setting, then retry |
| **Content** | Output was wrong | Retry with feedback (§5.6) | Force-apply, edit, discard |
| **Fatal** | `mico` is broken | None | Ledger entry |

### Why **Depleted** is separate from Config

Out-of-quota requires human action *or* the passage of time — it is a depletion, not a misconfiguration, and it resolves on its own at billing reset. Fail-fast-on-Config is correct at 3am for a bad API key, but permanently disabling schedules because quota ran out on the 28th is wrong when everything works again on the 1st.

Depleted therefore **suspends schedules with an automatic hourly re-probe** (single cheap call) rather than disabling them. Notification is informational, not an error. `retry-after` or a provider-supplied reset timestamp drives the re-probe when available.

### Classification of named failures

| Failure | Class | Notes |
|---|---|---|
| Network blip, connection reset, read timeout | Transient | |
| Provider 5xx | Transient | |
| Rate limited (429) | Transient | Distinct code — honour `retry-after` rather than own backoff curve |
| Transient MCP failure | Transient | |
| Out of quota / credits / hard cap | **Depleted** | |
| Task timeout | Budget | See discriminator below |
| Max validation retries exhausted | Budget | |
| Conflict retry limit reached | Budget | |
| Claude Code not installed / not authenticated | Config | |
| Invalid API key (401) | Config | |
| Insufficient permissions, model not enabled (403) | Config | Distinct code |
| Subscription doesn't permit programmatic invocation | Config | Distinct code — remedy is switching to an API key (§4.7) |
| Stage 2 provider unreachable | Config | See degradation rule below |
| Structurally invalid brief blocking a Run | Config | |
| Stage 1 rejection | Content | |
| Stage 2 rejection | Content | |
| No proposal written | Content | |
| Model refused the request | Content | Distinct code — user must see which content triggered it |
| Context window exceeded | **Content**, not Budget | Fix is smaller input, not a bigger allowance |
| Unhandled exception | Fatal | |

### Timeout ambiguity

Slow-network timeout is Transient; genuine long-work timeout is Budget. Same symptom.

**Partial discriminator:** no stream output at all → likely Transient (never got going; retry). Streamed then stalled → Budget (real work in progress; extend). Imperfect, but makes the default action usually right. Both affordances remain on offer either way.

### Retry bounds

Three, to prevent a local tool quietly burning budget overnight:

1. **Per-Run cap** on transient retries — 3, exponential backoff, jittered.
2. **Total wall-clock ceiling** across retries — retries do not reset the budget clock.
3. **Per-provider circuit breaker** — after N consecutive Transient failures, stop retrying anything for a cooldown and reclassify as Config. Twenty tracks retrying independently against a dead provider is the failure mode being prevented.

Scheduled Runs additionally **fail fast on Config-class errors**: no human will fix an API key at 3am, and hourly retries only fill the notification panel.

### Retry semantics

**A retry is always a fresh Run, never a resumed one.** New `run_id`, new sidecar, `base_revision` re-read at start (it may have moved), linked via `retry_of`.

- Reusing the Run ID makes the audit trail misreport how many agent invocations occurred.
- A stale `base_revision` reintroduces the AD-02 lost-update bug.
- **Idempotency:** each retry cleans up its predecessor's sidecar first, or orphan recovery surfaces superseded proposals.

**Extend is not a retry** (see AD-07).

### Two classifier adapters

Model errors arrive from two places, and identical symptoms mean different things:

- **Verification provider** — direct HTTP; `mico` sees raw status codes; classification is exact.
- **Claude Code** — errors arrive as agent output or a nonzero exit code; `mico` may get a message rather than a status, and Claude Code may already have retried internally.

Both adapters emit the same error shape. The agent adapter is inherently lossier; **where classification is ambiguous it defaults to Transient with a low retry cap** — retrying twice on something unretryable is cheap, while failing to retry something transient strands a Run.

### Optional-dependency degradation

Stage 2 is optional (§7.2), so verification-provider Depleted or Config failures **must not fail the Run**:

- `proposal` mode → commit as proposal, flag unverified, human reviews.
- `autonomous` mode → **must not silently commit unverified**; park in `awaiting_user_decision`.

The mandatory dependency (Claude Code) fails hard; the optional one degrades. 

### Error shape

One structure rendered by CLI, web UI, notification panel, and Ledger alike:

```
class:        transient | depleted | budget | config | content | fatal
code:         stable machine identifier (e.g. AGENT_TIMEOUT, STAGE1_STRUCTURE)
message:      human-readable, one line
detail:       structured, class-specific
affordances:  [retry, extend, abandon, force_apply, edit, fix_config, wait]
retry_count / retry_of
```

Stable codes are load-bearing: the notification panel groups on them, the Ledger deduplicates on them, and users search for them.

---

## AD-10 — Notification panel

**Status:** Decided

**Separate lightweight `notifications` table, not a Ledger view.** The Ledger is a durable issue tracker — things the user intends to fix. Notifications are transient events to acknowledge and forget. Merging them fills the issue list with "refresh completed successfully."

- Notifications **reference** their subject (`run_id`, `track_id`, `ledger_id`) rather than duplicating content, so click-through reaches the real record.
- **Includes successes**, muted: completions and pending approvals are precisely what the user wants after unattended overnight runs. Severity filtering keeps failures from being buried.
- Content is largely already generated by §7.4 loud failures and the health audit.

---

## AD-11 — Run as a persisted state machine

**Status:** Decided

**The Run row is written at start, not at end.** The orchestrator is a job runner with durable state, not a function returning a result.

Three independent requirements force this: orphan recovery must know a Run was in flight when the process died (§4.2); `proposal` mode parks indefinitely awaiting a human; timeout-extend must survive a restart.

Consequently **`status` is distinct from `outcome`** — status is where the Run is now, outcome is how it ended.

### States

**Active:**

```
running_agent → validating → committing → complete
```

**Parked** — all durable across restart:

| State | Entered on | Leaves when |
|---|---|---|
| `awaiting_approval` | `proposal` mode, validation passed | Human accepts or rejects |
| `awaiting_decision` | Content or Budget failure | Human force-applies, edits, or discards |
| `suspended` | Depleted (AD-09) | **Self-heals** on successful re-probe |
| `timed_out` | Budget exhaustion (AD-07) | Human extends or abandons |

**Terminal:** `complete`, `failed`, `abandoned`, `superseded`.

### No `queued` state

**Decided.** AD-02 permits mutating Runs to execute in parallel, serialising only at commit, so nothing queues. A scheduled Run skipped because a manual mutating Run is in flight is recorded as a Run going directly to `abandoned` with a reason — keeping the skip visible in history without adding a state.

### `suspended` is the only self-healing state

Every other parked state waits for a human. This makes the Depleted re-probe loop (AD-09) a genuine background component rather than a retry wrapper.

### `superseded` is load-bearing for the audit trail

When a conflict retry spawns a fresh Run (AD-02, AD-09), the original did not fail — it was correct and lost the race. Marking it `failed` would make §9's audit trail read as though something broke. `superseded`, carrying a pointer to the winning Run, keeps the trail honest.

---

## AD-12 — Notification reconciliation

**Status:** Decided

On startup, `mico` performs a **sweep** that re-hydrates parked Runs into the notification panel. This is what makes the panel worth having after unattended overnight runs.

### Notifications are state-derived, not event-emitted

The sweep does not *emit* notifications on discovering parked Runs. It **reconciles**: it computes the notification set implied by current Run state and makes the table match.

```
for each parked Run:
    upsert notification keyed on (run_id, reason)
```

**Idempotent by construction.** CLI and web server may sweep simultaneously and produce one row; the unique constraint on `(run_id, reason)` does the work. This eliminates the "who owns the sweep" and double-notification problems without coordination or locking.

It also makes the panel **self-healing**: a notification whose Run has since resolved is cleared by the next sweep rather than lingering.

**Sweep triggers:** process start (CLI and web), any Run transition into a parked or terminal state, and a low-frequency timer in the web server to catch schedule-driven changes.

### Two categories, different lifecycles

| | Actionable | Informational |
|---|---|---|
| **Source** | Derived from parked Run state | Event-emitted |
| **Examples** | Awaiting approval, timed out, awaiting decision | Completions, health findings, schedule skips, depletion notices |
| **Cleared** | Automatically, when the Run leaves the parked state | User dismissal; auto-expire after N days |
| **Dismissible** | **No** — dismissing would hide work still needing action | Yes |

Actionable notifications carry AD-09's `affordances` array directly, so the panel is where the user acts, not merely where they learn.

### Read vs. resolved

Do not model both. Actionable items are resolved-or-not, and that is derived. Informational items are read-or-not. A single `dismissed_at` field, meaningful only for informational entries.

### OS-level notifications

**Opt-in, off by default, actionable items only.** Unattended overnight runs are the point of autonomous mode; a panel visible only inside the app is seen only when the app is opened. Successes are excluded — a notification per completed refresh is noise that trains users to ignore the channel.

Storage: notifications reference their subject (`run_id`, `track_id`, `ledger_id`) rather than duplicating content, so click-through reaches the real record.

---

## AD-13 — Logging

**Status:** Decided

Dense logging gated by standard levels (`debug`, `info`, `warning`, `error`, `critical`), configurable via `--log-level` per invocation, a config default, and `MICO_LOG_LEVEL`.

### Structured, not string-formatted

JSON lines with typed fields. `run_id`, `track_slug`, `operation`, `error_class`, and `error_code` already exist as structured data; grepping formatted strings for a failing Run is precisely the debugging this decision exists to avoid.

### `run_id` as correlation ID

Propagated through a contextvar so every line emitted inside a Run carries it automatically, including from async tasks. Under AD-02's parallel Runs, interleaved logs are otherwise unreadable.

### Two sinks with different lifetimes

| Sink | Level | Purpose |
|---|---|---|
| Console | User-configured | Interactive feedback |
| `runs/<date>/<run_id>.jsonl` | Fixed, always written | Forensic record (§12.3) |

The Run log must not disappear because the console was set to `warning`. It is the artifact the audit trail and post-hoc debugging depend on.

### Redaction lives in the handler

**The scrubber sits in the logging pipeline, not at call sites.** A redaction step that depends on caller discipline will eventually leak. Key-shaped strings are stripped before any sink writes.

### Security tension with §12.3

Full prompts and agent output are written **only at `debug`**, because prompts contain the entire brief and all evidence — the most sensitive data in the system. Dense logging and this constraint coexist, but:

- `debug` is never the default.
- Enabling `debug` persistently in config triggers a first-run warning explaining that brief content will be written to disk.
- Run logs remain mode `0600` and outside `workspace/`, invisible to the agent (§3.1).

---

## Consolidated new/changed fields

**Run:** `base_revision`, `retry_of`, `superseded_by`, `status` (distinct from `outcome`), `run_config` (effective resolved), `error_class`, `error_code`.

**New tables:** `notifications`, `run_config` overrides (per-operation, per-track).

**Renamed:** `.proposed.md` → `.proposed.<run_id>.md`.

**New Run outcomes:** `timed_out`, `conflict`, `depleted`, `superseded`.

---

---

## AD-14 — Technology stack and dependency policy

**Status:** Decided

### Governing constraint

The author works at an enterprise where all dependencies require approval. **Only well-established, highly-ranked, actively-maintained libraries are permitted. Adding dependencies is minimised as a first-order design concern**, not a tie-breaker.

Consequence: where a candidate library is a thin wrapper over something the standard library already does, the wrapper is rejected and a small internal equivalent is written instead. The code written this way is small, owned, and testable.

### Runtime dependencies (approved set)

| Dependency | Purpose | Notes |
|---|---|---|
| FastAPI | Web backend | |
| Pydantic v2 | Validation, domain models, API schemas | Used throughout, not only at boundaries — validation cost is irrelevant at this scale |
| Typer | CLI framework | |
| Rich | CLI rendering, agent stream display | |
| PyYAML | Brief frontmatter | |
| Jinja2 | Prompt templates; server-side rendering if needed | |
| httpx | Async HTTP to the verification provider | No stdlib async HTTP equivalent |
| keyring | Credential storage (§12.1) | `pip` itself depends on it, which assists approval |
| pytest (+ pytest-asyncio) | Testing | Dev only |

**Eight runtime dependencies**, all mainstream. Scheduling adds none (AD-15).

### Rejected in favour of stdlib

| Rejected | Replacement | Rationale |
|---|---|---|
| `aiosqlite` | `sqlite3` + threadpool executor, ~40-line internal wrapper | aiosqlite *is* a threadpool wrapper; the dependency buys syntax only |
| `structlog` | `logging` + JSON `Formatter` + `contextvars` `Filter`, ~60 lines | AD-13 needs JSON output, `run_id` propagation, and redaction — a formatter and a filter |
| `python-frontmatter` | Split on `---`, hand the block to PyYAML | Small library wrapping a small operation |
| `yoyo-migrations` / Alembic | Numbered `.sql` files + `PRAGMA user_version` | Forward-only, tiny schema; Alembic assumes SQLAlchemy |
| `tomli-w` | TOML read-only via stdlib `tomllib`; mutable state in SQLite | Removes the write dependency entirely |
| `plyer` | `subprocess` to `osascript` / `notify-send` / PowerShell, **or defer** | Low-rank and flaky; AD-12 has OS notifications opt-in and off by default, so deferring is cheap |
| `import-linter` | ~50-line AST script asserting layer rules | Dev dependencies also require approval |
| SQLAlchemy Core | Narrow port (AD-04) | Scale removes its advantages; recorded there as a deliberate choice |

### Scheduling — no dependency (see AD-15)

APScheduler and croniter are both **rejected**. Scheduling is implemented against an internal abstraction over structured schedule fields. Full rationale in AD-15.

### Frontend — React + Vite (author decision)

**React + React DOM + Vite + TypeScript.** Chosen over the lower-dependency alternative on interaction-model grounds: the live agent chat stream and dual-pane workspace justify it.

**Recorded risk:** an npm tree is the single largest dependency-approval surface in the project, far exceeding the ten Python packages. Mitigations, to be applied from the first commit:

- **Pin exact versions and commit the lockfile** — the approval surface is a fixed, auditable list, not a moving tree.
- **Deliberately minimal dependency list** — React, React DOM, Vite, TypeScript only. No component library, no state manager, no date library.
- **Commit built assets**; build runs in CI. End users installing `mico` pull **zero** JavaScript packages, satisfying OPEN-12.
- Adding a component library later re-opens this decision rather than passing silently.

**Rejected: HTMX + Jinja2.** A single vendored script, no build step, no `node_modules`, native SSE for the AD-05 stream. Materially lower approval risk; rejected on interaction quality. Remains the fallback if npm approval fails.

### Configuration format

**TOML read-only via stdlib `tomllib`.** All mutable state lives in SQLite, consistent with AD-08 where `run_config` overrides are already database-backed. `config.toml` stays hand-editable; no write library required.

### Packaging

`uv` for development, `pipx` / `uv tool install` for end users, `hatchling` as build backend. Development tooling typically clears a lower approval bar than runtime dependencies; falls back cleanly to `pip` + `venv` if not.

### Flagged technical risk

**Subprocess streaming.** `asyncio.create_subprocess_exec` with incremental JSON-lines parsing of stdout, plus reliable kill-and-reap on timeout (AD-07). Historically the weakest part of asyncio on Windows, which is Tier 2 (§11.4). **Warrants a spike early in M2 rather than an assumption.**

---

## AD-15 — Scheduling: structured schedules, no dependency

**Status:** Decided

### Why not APScheduler

Interrogating the actual need showed we require **one** hard thing from a scheduler library: given a schedule and a timestamp, compute the next fire time. Everything else APScheduler provides is already specified elsewhere in this design and would be duplicated:

| APScheduler feature | Already ours |
|---|---|
| Job store | Schedules in SQLite (§11.1, with `execution_mode`) |
| Misfire handling | Coalesce semantics defined in §11.2 |
| Executors | Run state machine (AD-11) |
| Job lifecycle | Run `status` — richer than APScheduler models |

**The conceptual objection:** APScheduler wants to own job identity and job state; we already own Run identity and Run state. Two overlapping state models sharing responsibility for "did this run" is a reliable source of divergence bugs — a Run marked `abandoned` while the scheduler believes the job succeeded. We would be using ~5% of a large library, and that 5% would fight our own design.

**Version status also disqualified it independently:** as of mid-2026 the stable line is 3.11.3 while 4.0 remains a pre-release whose own documentation warns of backwards-incompatible change without a migration pathway. 4.0 is async-first and would have suited AD-01 better.

### Why not croniter either

Investigated as a narrow replacement providing only next-fire calculation. Findings:

**In favour:** 6.2.4 released July 2026, steady cadence, MIT, packaged in Debian and Fedora/EPEL, ~7.6M weekly downloads, Snyk rates maintenance healthy with no known vulnerabilities. Authors include Airflow committers.

**Against, under this project's dependency policy:**

1. **Near-death event.** In late 2024 the maintainers declared intent to end development and possibly unpublish, over EU Cyber Resilience Act concerns. It survived and moved to the pallets-eco organisation, but the episode is on record.
2. **~551 GitHub stars** despite the download volume — fails a stars-based screen while passing a usage-based one.
3. **PyPI classifier is "4 - Beta"** — cosmetic for a 16-year-old library, but it is what an automated policy check reads.
4. **Two transitive dependencies** — `python-dateutil` and `pytz`. Three packages, not one.

### The decisive constraint: coarse resolution

**Minute-level granularity is sufficient. A job firing at 02:15 instead of 02:00 is operationally irrelevant.**

Cron parsing is hard because of `*/7`, ranges, day-of-month/day-of-week interaction, `L`, `#`, and second-level precision. **None of that is needed.** Real schedules for this tool are: daily at a time, weekly on given days at a time, every N hours.

### Design

Schedules are stored as **structured fields, not cron strings**:

```
frequency:      daily | weekly | interval
time_of_day:    08:00
days_of_week:   [MO, WE, FR]
interval_hours: 6
timezone:       (IANA name, via stdlib zoneinfo)
```

Next-fire calculation over these fields is ordinary `datetime` arithmetic — a few dozen lines. **`zoneinfo` (stdlib) handles the DST cases** that made cron parsing worth outsourcing in the first place.

**Crontab export becomes formatting, not parsing** — structured fields → `0 8 * * 1,3,5`. One direction only, entirely under our control. The APScheduler weekday-numbering trap (`0` = Sunday in crontab, Monday in APScheduler 3.x) disappears, because we write the mapping ourselves rather than inheriting a library's convention.

**The runner** is an asyncio loop that wakes on a coarse timer, asks each enabled schedule for its next fire time, and starts a Run. Approximately 100 lines, fitting the AD-11 state machine natively rather than bridging into it.

**Net: zero scheduling dependencies.** APScheduler, croniter, `tzlocal`, `python-dateutil`, and `pytz` all drop out.

### Abstraction requirement

Per project guidelines, the implementation sits behind an interface so it can be replaced:

- `ScheduleSpec` — the structured schedule value object.
- `NextFireCalculator` (ABC) — `next_fire_after(spec, after: datetime) -> datetime | None`. The internal implementation is one subclass; a croniter- or APScheduler-backed subclass may be added later without touching the runner.
- `Scheduler` (ABC) — start, stop, register, and the wake loop, so the embedded runner can be swapped.

### Accepted limitation

**Arbitrary cron expressions cannot be pasted in.** Accepted for v1 — schedules are built through the UI or CLI flags. If demand appears, a restricted cron-subset parser is a small addition behind `NextFireCalculator`, and the export path already speaks crontab.

---

## Still open — deferred to HLD

- **Commit atomicity: journal file necessity** (AD-03). Needs the transaction design in front of it.
- **Full error-code catalogue** (AD-09). Enumeration, not decision.
- **Service layer command/result contract detail** (AD-06).
- **Sidecar lifecycle state machine and orphan recovery** (PRD §4.2).
- **Exhaustive Stage 1 check list with thresholds** (PRD §7.1).

## Closed during this review

#1 async core (AD-01) · #2 Run state machine (AD-11) · #3 commit atomicity approach (AD-03) · #4 storage interface (AD-04) · #5 agent process ownership (AD-05) · #6 service layer shape (AD-06) · concurrency and conflict handling (AD-02) · timeouts and budgets (AD-07) · run configuration (AD-08) · error handling scheme (AD-09) · notifications (AD-10, AD-12) · logging (AD-13) · unit-of-work (folded into AD-04).
