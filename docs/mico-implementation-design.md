# `mico` Implementation Design

## Context

`mico` ("Mission Control") is fully speced in two docs — `docs/mico-prd-v3.md` (PRD v3.0.0) and `docs/mico-architecture-decisions.md` (15 architecture decisions from pre-HLD review). This document turns that spec into an actionable build plan: implementation decisions distilled into concrete tasks, the dependency graph between those tasks, a build order, and which tasks can run in parallel. The PRD already defines four milestones (M1–M4); this design decomposes each into dependency-tracked tasks so the milestones become executable rather than aspirational.

Core shape, from the docs: `mico` never talks to third-party services or holds their credentials — Claude Code (invoked as a subprocess) does the reading/writing of external sources, and `mico` is schema-owner/orchestrator/validator/store around it. State moves only through a file-based "sidecar" (`.proposed.md`), never through parsed agent transcript. Storage is hybrid — Markdown briefs on disk (authoritative for content) + SQLite (authoritative for everything else) behind a narrow `MetadataStore` port. Validation is a mandatory deterministic Stage 1 plus an optional LLM-grounding Stage 2. Everything (Runs, retries, scheduling, notifications) is modeled as a persisted state machine so unattended/overnight operation is debuggable and recoverable.

## Governing Implementation Decisions (from the docs, drive task shape)

| Decision | Consequence for tasks |
|---|---|
| AD-01 Async core, sync CLI wrapper | `mico/brain` and `mico/logic` are async top-to-bottom; CLI wraps with `asyncio.run()`. |
| AD-02 Optimistic per-track concurrency | Commit path needs `base_revision` check + short per-track lock, not a job queue. |
| AD-03 Commit atomicity | SQLite transaction + temp-file/`os.replace()` write, wrapped in a shared unit-of-work. |
| AD-04 Narrow `MetadataStore` port | ~12 abstract primitives (Records/Queries/Transaction/Schema/Search) + one shared concrete layer (~60 call sites) on top, not per-aggregate repositories. In-memory fake is a first-class deliverable (it's the actual M1 acceptance bar). |
| AD-05 No persistent agent process | Every turn is a fresh `claude -p [--resume]`; no process pool/supervisor to build. |
| AD-06 Service layer shape | Facade with command/result dataclasses, shared verbatim by CLI and web. |
| AD-07/AD-08 Budgets, timeouts, run_config | Per-stage internal timeouts, one user-facing budget, four-level config resolution (global→operation→track→run), extend-vs-abandon on timeout. |
| AD-09 Error classification | Six classes (transient/depleted/budget/config/content/fatal) drive one uniform error shape and retry policy; two adapters (HTTP vs Claude Code) feed it. |
| AD-10/AD-12 Notifications | Separate `notifications` table, populated by idempotent state-reconciliation sweep, not event emission for actionable items. |
| AD-11 Run as persisted state machine | Run row written at start; `status` ≠ `outcome`; parked states must survive restart. |
| AD-13 Logging | Structured JSON, `run_id` via contextvar, redaction in the handler, two sinks. |
| AD-14 Dependency policy | Minimal runtime deps (8 Python packages, listed in PRD §17); several "obvious" libraries (aiosqlite, structlog, croniter, APScheduler, python-frontmatter) are deliberately replaced by small internal code — tasks below build those internal equivalents instead of pulling the library. |
| AD-15 Scheduling without a library | `ScheduleSpec` + `NextFireCalculator` ABC + stdlib `zoneinfo` arithmetic, not cron parsing. |

Layering is enforced throughout: `mico/brain/` (storage, schemas, migrations) ← `mico/logic/` (orchestration, agent, validators, scheduler) ← `mico/ui/cli/` and `mico/ui/web/`. `ui` may never import `brain` directly (PRD §15.1); this is CI-enforced by a small AST script, not just convention.

## Technology Stack

The docs specify this explicitly (PRD §17, AD-14) — it is not something this design chose, only inventoried and checked for gaps.

**Backend**

| Layer | Choice | Source |
|---|---|---|
| Language | Python 3.11+ | PRD §17 |
| Web framework | FastAPI | PRD §17, AD-14 |
| Validation/domain models | Pydantic v2 (used throughout, not just at API boundaries) | AD-14 |
| CLI framework | Typer | AD-14 |
| CLI rendering / agent stream display | Rich | AD-14 |
| Brief frontmatter parsing | PyYAML (hand-split on `---`, no `python-frontmatter`) | AD-14 |
| Prompt templates | Jinja2 | AD-14 |
| Async HTTP (Stage 2 verification calls) | httpx | AD-14 (no stdlib async HTTP equivalent) |
| Credential storage | `keyring`, `.env` (mode 0600) fallback | AD-14, PRD §12.1 |
| Storage | Markdown files (briefs) + SQLite, WAL mode | PRD §17, §3.1 |
| Config format | TOML, stdlib `tomllib` (read-only; all mutable state in SQLite) | AD-14 |
| Scheduling | Internal asyncio loop over structured fields + stdlib `zoneinfo`, **no scheduling library** | AD-15 |
| Agent integration | Claude Code CLI via subprocess (`claude -p --output-format stream-json`) | PRD §17, §4 |
| Testing | pytest + pytest-asyncio (dev only) | AD-14 |
| Packaging | `uv` (dev), `pipx`/`uv tool install` (end users), `hatchling` (build backend) | AD-14 |
| Layer-boundary enforcement | Hand-rolled ~50-line AST script (rejected `import-linter` — dev deps also need approval) | AD-14 |

That's the full **8 runtime dependencies** AD-14 commits to: FastAPI, Pydantic, Typer, Rich, PyYAML, Jinja2, httpx, keyring. Everything else (JSON logging, SQLite migrations, unit-of-work, redaction, word-count, query spec) is deliberately hand-rolled per AD-14's dependency-minimization policy — those are still real implementation tasks (see M1.2, M1.5, M1.7, M2.6), just not new libraries.

**Frontend**

| Layer | Choice | Source |
|---|---|---|
| Framework | React + React DOM | AD-14 (author decision) |
| Build tool | Vite | AD-14 |
| Language | TypeScript | AD-14 |
| Component library | **None, deliberately** | AD-14 |
| State management | **None, deliberately** — no Redux/Zustand/etc. | AD-14 |
| Date library | **None, deliberately** | AD-14 |
| Streaming transport | SSE (Server-Sent Events) from the FastAPI backend, polling fallback | PRD OPEN-10 |
| Deployment model | Exact-pinned deps, committed lockfile, **built assets committed to the repo** — end users installing `mico` pull zero npm packages | AD-14 |
| Fallback (if npm approval fails) | HTMX + Jinja2, vendored, no build step | AD-14, explicitly recorded as fallback not primary path |
| FE unit/component tests | Vitest + React Testing Library | Added — resolves gap below |
| FE end-to-end tests | Playwright | Added — resolves gap below |

**Gaps found, and how they're resolved:**

1. **Snapshot encryption (OPEN-4)** — confirmed **deferred to post-v1**. Snapshots (§10) ship in v1 without `--encrypt`; see the Deferred section below.
2. **Dev tooling (lint/format/typecheck)** — resolved as: ruff + mypy, the low-friction choices given the rest of the stack.
3. **Frontend testing** — resolved: Vitest + React Testing Library for unit/component tests, Playwright for e2e. Tasks M4.15/M4.16 below, built incrementally alongside each view rather than as one terminal task.
4. **Global search / FTS5 (OPEN-9)** — confirmed **deferred to post-v1**. See the Deferred section below.

Everything else the docs specify — every entry in the two tables above — is fully accounted for somewhere in the task breakdown below.

**Deferred to post-v1 (out of scope for the task list and waves that follow):**

| Item | PRD ref | Why it's not in v1 scope | Re-entry point when built |
|---|---|---|---|
| Snapshot encryption (`--encrypt`) | §10, OPEN-4 | Confirmed future requirement — snapshots ship unencrypted in v1; `--encrypt` is for the later case of syncing snapshots to a private git remote | Add as a flag on the existing `mico snapshot create` command (M3.15) plus a library decision (`cryptography` vs. `age`/`gpg`) — additive, not a rework |
| Global search (Cmd/Ctrl+K, SQLite FTS5) | §13.2, OPEN-9 | Confirmed future requirement | Add an FTS5 virtual table + migration (extends M1.7/M1.8) plus a search endpoint/UI affordance (extends M4.2/M4.5) — additive, not a rework |

Both are structured so v1 doesn't have to design around them, but doesn't preclude them either — same posture the PRD itself takes toward other deferred items (§1.3, §4.8).

---

## Task Breakdown by Milestone

Each task has an ID, a one-line scope, and its dependencies (by ID). IDs match the PRD's M1–M4 grouping. Under the Delivery Process below, each row is also one PR.

### M1 — Core Interfaces & Storage

| ID | Task | Depends on |
|---|---|---|
| M1.1 | Project scaffolding: `pyproject.toml` (uv/hatchling), package layout (`mico/brain`, `mico/logic`, `mico/ui/cli`, `mico/ui/web`), pytest+pytest-asyncio setup, import-linter-equivalent AST script enforcing layer rules, **plus CI bootstrap** — `.github/workflows/ci.yml` (lint/typecheck/test/layer-check/build jobs) and the automated PR-review workflow (see Delivery Process below), so every PR from M1.2 onward is gated from day one | — |
| M1.2 | Structured logging (AD-13): JSON `Formatter`, `run_id` contextvar `Filter`, redaction scrubber, console + `runs/<date>/<run_id>.jsonl` sinks, `--log-level`/`MICO_LOG_LEVEL` | M1.1 |
| M1.3 | Domain models (Pydantic v2): `Track`, brief frontmatter model, `BriefRevision`, `EvidencePointer`, `Run`, `LedgerEntry`, `Schedule`, `Notification`, all enums from PRD §2 | M1.1 |
| M1.4 | Shared word-count utility (PRD §2.2 — one implementation used by prompt assembly, Stage 1, health audit) | M1.1 |
| M1.5 | Declarative query-spec object (field/op/value predicates, AND/OR, order/limit/offset, closed operator set) | M1.1 |
| M1.6 | `MetadataStore` ABC — narrow port: Records (insert/get/update/delete/upsert), Queries (`query`/`count`/`exists`), Transaction (begin/commit/rollback), Schema (migrate/current_version), optional Search | M1.5 |
| M1.7 | SQLite migration framework: numbered `.sql` files + `PRAGMA user_version` | M1.1 |
| M1.8 | SQLite `MetadataStore` implementation (WAL mode; `sqlite3` + threadpool executor per AD-14, not `aiosqlite`) | M1.6, M1.7, M1.3 |
| M1.9 | In-memory `MetadataStore` fake | M1.6, M1.3 |
| M1.10 | Concrete shared query layer on the port (`get_active_tracks`, `latest_revision`, `revisions_since`, `dead_pointers_for_track`, `parked_runs`, `open_ledger_entries`, `unresolved_notifications`, …) | M1.6, M1.9 |
| M1.11 | `BriefStore` (filesystem): `workspace/tracks/<slug>/brief.md`, `.proposed.<run_id>.md` sidecar naming, atomic write via temp file + `os.replace()` | M1.1, M1.3 |
| M1.12 | Single-source-of-truth reconciliation (PRD §3.2): SHA-256 compare on read, `user_edit` revision on mismatch, `structurally_invalid` flagging | M1.11, M1.8 |
| M1.13 | Locking: `$MICO_HOME/.lock` single-writer (`flock`/`msvcrt`, 30s timeout naming holder), per-track logical lock | M1.1 |
| M1.14 | Transaction/unit-of-work context manager wrapping brief write + Revision row + evidence index rows + Track timestamp (AD-03, AD-04) | M1.6, M1.8 |
| M1.15 | Schema versioning + startup migration + automatic pre-migration snapshot (PRD §3.4) | M1.7, M1.8 |
| M1.16 | `mico reindex` — rebuild derivable SQLite state from files | M1.10, M1.12 |
| M1.17 | Track service (create/list/update/archive) in `mico/logic` | M1.10, M1.3 |
| M1.18 | CLI scaffolding (Typer) + track commands | M1.17 |
| M1.19 | **Acceptance test:** full pipeline green against the in-memory `MetadataStore` (AD-04's actual M1 bar, not vendor swap) | M1.9, M1.10, M1.17 |

### M2 — Agent Integration & Validation

| ID | Task | Depends on |
|---|---|---|
| M2.1 | `AgentProvider` ABC | M1.1 |
| M2.2 | **Spike:** Claude Code subprocess wrapper — `asyncio.create_subprocess_exec`, incremental `stream-json` parsing, kill-and-reap on timeout/cancel (flagged risk, AD-14 — start early) | M2.1 |
| M2.3 | Mock agent provider — writes fixture `.proposed.md` (PRD §15.4, the key offline-testability affordance) | M2.1 |
| M2.4 | Prompt template system (Jinja2, versioned templates, template IDs recorded on Run) | M1.1, M1.3 |
| M2.5 | Run state machine (AD-11): row written at start; `running_agent→validating→committing→complete`; parked states `awaiting_approval`/`awaiting_decision`/`suspended`/`timed_out`; terminal states incl. `superseded` | M1.8, M1.9, M1.3 |
| M2.6 | Error classification scheme (AD-09): six classes, uniform error shape, HTTP + Claude-Code classifier adapters, retry-bound/circuit-breaker logic | M1.1 |
| M2.7 | Sidecar contract (PRD §4.2): pre-populate `.proposed.md`, invoke agent with cwd=track dir, read+validate on completion, accept/reject, startup orphan-recovery scan | M1.11, M2.2, M2.3, M2.5 |
| M2.8 | Scoping enforcement (PRD §4.4/4.5): cwd restriction per operation class, `--allowedTools` allowlist, no `--dangerously-skip-permissions` | M2.2 |
| M2.9 | Stage 1 deterministic validator (9 checks, PRD §7.1) + malformed-proposal fixture corpus | M1.3, M1.4, M2.4 |
| M2.10 | Retry & termination (PRD §5.6): max 2 retries w/ structured feedback, 3-consecutive-rejection escalation to Ledger | M2.9, M2.6, M2.5 |
| M2.11 | Concurrency/optimistic locking (AD-02): `base_revision` capture, per-track commit-time lock, conflict resolution (`autonomous`=reject-and-rerun, `proposal`=reject-and-surface) | M1.14, M2.5 |
| M2.12 | `run_config` resolution chain + timeout extend/abandon (AD-07/AD-08) | M2.5, M1.3 |
| M2.13 | Service-layer facade (AD-06): command/result dataclasses for `refresh`/`condense`/`task`/`chat`/`ask`/`recap`/`delta`/`evidence`/`artifact` | M2.7, M2.9, M2.10, M2.11, M2.12, M1.17 |
| M2.14 | CLI interactive `mico chat <slug>` (REPL, per-turn `--resume`, Rich stream rendering) | M2.13, M2.2 |
| M2.15 | Session persistence (`agent_session_id` storage, `--save` transcript) | M2.14 |
| M2.16 | `mico doctor` (Claude Code binary/version/auth check) | M2.2 |
| M2.17 | **Acceptance test:** full `refresh` end-to-end against the mock agent, offline; every Stage 1 check has a failing fixture; scoping verified by asserting the agent cannot read outside `workspace/` | M2.3, M2.13 |

### M3 — Automation, Health, Ledger & Audit

| ID | Task | Depends on |
|---|---|---|
| M3.1 | `VerificationProvider` ABC | M1.1 |
| M3.2 | Stage 2 HTTP client (httpx, stateless call) | M3.1 |
| M3.3 | Stage 2 grounding validator + rubric split (refresh vs. condense loss-rubric) + raw-score persistence (feeds OPEN-2) | M3.2, M2.9, M2.13 |
| M3.4 | Local-model Stage 2 backend (swap-provider acceptance test) | M3.1, M3.3 |
| M3.5 | Automation modes (PRD §5.8): per-track mode, manual promotion only, `autonomous` requires Stage 2 configured, force-downgrade after 3 rejections | M3.3, M2.10, M1.3 |
| M3.6 | `ScheduleSpec` + `NextFireCalculator` ABC + internal `zoneinfo`-based implementation (AD-15) | M1.1 |
| M3.7 | `Scheduler` ABC + embedded asyncio runner; skip-if-manual-mutating-run-in-flight (AD-02) | M3.6, M2.13, M2.11 |
| M3.8 | Schedule persistence/CRUD (structured fields, PRD §11.1) | M1.6, M1.8, M3.6 |
| M3.9 | Misfire handling — coalesce/skip/run_all (PRD §11.2) | M3.7 |
| M3.10 | External schedule export (crontab/systemd/launchd/taskscheduler) + `mico schedule doctor` | M3.8 |
| M3.11 | Depleted-class self-healing re-probe loop | M2.6, M3.7 |
| M3.12 | Ledger table + CRUD (PRD §2.6) | M1.6, M1.8 |
| M3.13 | Health audit engine: staleness index, within-track then cross-track candidate-filtered contradiction detection, dead-reference flagging, bloat, unattributed-statement trend (PRD §8) | M1.10, M3.12, M3.2 |
| M3.14 | Notifications (AD-10/AD-12): table, idempotent reconciliation sweep, actionable-vs-informational lifecycle, opt-in OS notifications | M2.5, M3.12 |
| M3.15 | Snapshots: create/restore (unencrypted — `--encrypt` deferred, see Deferred section above), manifest w/ `schema_version`, replace/merge modes | M1.15, M3.12, M3.8 |
| M3.16 | Audit trail (`mico audit`) — view joining Revisions + Runs, no new storage | M1.3, M2.5 |
| M3.17 | Issue export flow (PRD §12.4, OPEN-5): default-deny allowlist, exact-payload confirmation, path scrubbing | M3.12 |

### M4 — Web UI & REST API

| ID | Task | Depends on |
|---|---|---|
| M4.1 | FastAPI scaffolding: localhost-only bind, session token, CSRF, Origin/Host validation, CSP (PRD §12.2) | M2.13 |
| M4.2 | REST endpoints for every PRD §5.1 operation (thin binding, no logic in `ui/`) | M4.1, M2.13 |
| M4.3 | SSE streaming endpoint for live agent output (resolves OPEN-10) | M4.2, M2.14 |
| M4.4 | React+Vite+TypeScript scaffold — minimal deps, pinned+locked, build committed (AD-14) | M1.1 |
| M4.5 | Overview Dashboard view | M4.2, M4.4 |
| M4.6 | Track Grid/List view | M4.2, M4.4 |
| M4.7 | Interactive Workspace (dual-pane: brief + live chat) | M4.3, M4.4 |
| M4.8 | General Workspace (knowledge editor + `ask` console) | M4.2, M4.4 |
| M4.9 | Administrative Hub (credentials, doctor, schedules, snapshots, ledger/export, audit) | M4.2, M4.4, M3.15, M3.17 |
| M4.10 | Track Summary Card component | M4.4 |
| M4.12 | Manual track ordering (resolves OPEN-11) | M1.3, M4.6 |
| M4.13 | Credential management UI wiring (keyring/.env) | M4.9 |
| M4.14 | End-to-end security checklist pass (PRD §12.2) | M4.5–M4.13 |
| M4.15 | FE unit/component test harness (Vitest + React Testing Library); tests written incrementally alongside M4.5–M4.13, not after | M4.4 |
| M4.16 | FE end-to-end test suite (Playwright) covering core flows: track list → workspace → chat, `ask` console, admin hub/export confirmation | M4.5, M4.6, M4.7, M4.8, M4.9 |

---

## Delivery Process: Commits, PRs, and the CI Gate

Implementation proceeds as **one PR per task ID** by default (the Task Breakdown table above is therefore also the PR list), merged into `main` only when CI is fully green — and CI includes an automated review, not just tests.

### Branching & PR granularity

- One feature branch and one PR per task ID (`M1.1`, `M1.2`, …), e.g. branch `feat/m1-2-logging` → PR titled `M1.2: structured logging (AD-13)`.
- **Combine only when a task has no independent test surface of its own** — e.g. a one-line constant added to an already-open PR doesn't need its own branch. Default is 1:1; don't split further than the table, don't merge across waves.
- PR description must state: which task ID(s) it implements, which PRD/AD sections it satisfies, and what tests were added — this is what the review gate checks against (below).
- A PR may branch off an unmerged dependency's branch (per the dependency column), but **must not merge into `main` until every task it depends on is already merged** — `main` always stays a consistent, dependency-correct snapshot. This is what makes the wave ordering enforceable in practice, not just on paper.

### CI pipeline (required status checks on every PR into `main`)

| Job | What it does | Blocks merge on |
|---|---|---|
| `lint` | ruff (backend); eslint (frontend, from M4.4 onward) | any error |
| `typecheck` | mypy (backend); `tsc --noEmit` (frontend) | any error |
| `test` | pytest (+coverage) for backend tasks; Vitest for frontend tasks (M4.15+); Playwright for the e2e suite (M4.16) | any failing test, or coverage regression on touched files |
| `layer-check` | the AST script from M1.1 — `ui/` importing `brain/` directly fails the build | any violation |
| `build` | `hatchling` build sanity; `vite build` once frontend exists | build failure |

All required as **branch-protection required status checks** on `main`: no merge while any job is red, no direct pushes to `main`, PR must be up to date with `main` before merging.

### Automated code-review gate (required check, separate from `test`)

A dedicated CI job runs an LLM-driven review of the diff on every PR and posts findings as a PR review. It is a required status check like the others: **a PR cannot merge while this check is red**, same as a failing test. It verifies, against the PR description's stated task ID and this design doc:

1. **Requirements coverage** — the diff actually implements what the linked task ID and PRD/AD section call for, not a partial stand-in.
2. **Test coverage** — every new function/branch/ABC method has a corresponding test; nothing new lands untested.
3. **Coding standards**, specifically:
   - Security (secrets never logged/committed, subprocess/file-path handling — most relevant to M2's Claude Code subprocess work — injection-safe SQL via the query-spec object, not raw strings)
   - Simplicity and reuse — no duplicate logic, particularly relevant given AD-04's "12 abstract primitives + one shared concrete layer" design, which this check exists partly to keep honest
   - No magic numbers/hardcoded strings — thresholds (word-count limits, retry counts, timeout defaults) live in config/constants, not inline literals
   - Encapsulation — layer boundaries (`brain`/`logic`/`ui`) and ABC boundaries (`MetadataStore`, `AgentProvider`, `VerificationProvider`, `Scheduler`, `Validator`) respected, no reaching around an interface
   - Correct API shape for whichever ABC the task implements, checked against its contract in this design and in AD-04/AD-15/PRD §15.2

A finding at high/critical severity fails the check; the PR author (or the next session picking up the task) fixes and re-pushes, same as a failing test would require.

### One-time setup (do once, as part of or right after M1.1)

- Enable branch protection on `main` in the GitHub repo settings: require the five CI jobs above + the review-gate check, require PRs (no direct pushes), require branches up to date.
- `review-gate` authenticates via **Anthropic Workload Identity Federation (WIF)**, not a static `ANTHROPIC_API_KEY` secret: the job exchanges its GitHub Actions OIDC token for a short-lived Anthropic access token using `anthropics/claude-code-action@v1` (`id-token: write` permission, plus a federation rule/service account already configured in the Anthropic Console). No repo secret is required or stored for this job — instead, set four repo **variables** (Settings → Secrets and variables → Actions → Variables tab, not Secrets, since these are identifiers rather than credentials): `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID`, `ANTHROPIC_WORKSPACE_ID`.

---

## Implementation Order (topological, by wave)

Waves are built so everything in a wave only depends on tasks in earlier waves; tasks within a wave have no dependency on each other and are the "parallel" candidates.

**Wave 0**
`M1.1`

**Wave 1** *(parallel)*
`M1.2, M1.3, M1.4, M1.5, M1.7, M1.13, M2.1, M2.6, M3.1, M3.6, M4.4`
*(logging, domain models, word-count util, query spec, migration framework, locking, the agent/verification ABCs, the scheduler value objects, and the frontend scaffold are all independent of each other once M1.1 lands — this is the widest parallel front in the project.)*

**Wave 2** *(parallel)*
`M1.6` (needs M1.5) · `M1.11` (needs M1.3) · `M2.2` (needs M2.1 — **start this spike as early as possible**, it's the flagged technical risk) · `M2.3` (needs M2.1) · `M2.4` (needs M1.3) · `M3.2` (needs M3.1)

**Wave 3** *(parallel)*
`M1.8, M1.9` (both need M1.6/M1.7/M1.3) · `M2.8` (needs M2.2)

**Wave 4** *(parallel)*
`M1.10, M1.14` (need M1.8/M1.9) · `M1.12` (needs M1.11+M1.8) · `M2.5` (needs M1.8/M1.9) · `M2.9` (needs M2.4) · `M3.3` (needs M3.2 — also needs M2.9/M2.13, see note below)

**Wave 5** *(parallel)*
`M1.15, M1.16, M1.17` · `M2.7` (needs M1.11+M2.2/M2.3+M2.5) · `M2.11, M2.12` (need M2.5/M1.14) · `M3.4` (needs M3.3) · `M3.12` (needs M1.8)

**Wave 6** *(parallel)*
`M1.18, M1.19` · `M2.10` (needs M2.9/M2.6/M2.5)

**Wave 7**
`M2.13` — the service-layer facade; it fans in almost everything from M2, so it's a natural sync point.

*(M3.3/M3.5 formally need M2.13 to exist for Stage-2-in-the-loop testing; treat M3.2/M3.4's provider-only work as done in earlier waves and slot the M2.13-dependent validation wiring here.)*

**Wave 8** *(parallel)*
`M2.14, M2.16, M2.17` · `M3.5` (needs M3.3+M2.10) · `M3.7` (needs M3.6+M2.13+M2.11) · `M3.13` (needs M1.10+M3.12+M3.2) · `M3.14` (needs M2.5+M3.12) · `M3.16` (needs M1.3+M2.5) · `M3.17` (needs M3.12) · `M4.1` (needs M2.13)

**Wave 9** *(parallel)*
`M2.15` · `M3.9, M3.11` (need M3.7) · `M3.8` (needs M3.6/M1.8 — can slide earlier if scheduler value objects are ready sooner) · `M4.2` (needs M4.1)

**Wave 10** *(parallel)*
`M3.10` (needs M3.8) · `M3.15` (needs M1.15+M3.12+M3.8) · `M4.3` (needs M4.2) · `M4.5, M4.6, M4.8` (need M4.2+M4.4, can start once M4.4 is ready even earlier — see parallel note)

**Wave 11** *(parallel)*
`M4.7` (needs M4.3) · `M4.9` (needs M4.2/M4.4+M3.15+M3.17) · `M4.10, M4.12` (need M4.6)

**Wave 12**
`M4.13` (needs M4.9) → `M4.16` (needs M4.5–M4.9, runs alongside M4.13) → `M4.14` (needs all M4 views) — final security pass, closes the project.

*(M4.15 isn't a wave — it starts as soon as M4.4 lands, in Wave 2, and runs continuously alongside every FE task from there on, same as tests generally do; it's listed as a discrete task only so it doesn't get silently skipped.)*

---

## Cross-Milestone Parallel Tracks (team-of-N view)

If more than one person/session is building this, the dependency graph supports genuinely independent tracks, not just wave-by-wave lockstep:

1. **Storage track:** M1.1 → M1.5/M1.6/M1.7 → M1.8/M1.9 → M1.10/M1.14 → M1.12/M1.15/M1.16. Fully self-contained until M1.17.
2. **Agent-integration track:** M2.1 → M2.2 (the risk spike — get someone on this immediately after M1.1, don't wait for storage to finish) → M2.3/M2.8. Only needs `AgentProvider` ABC + M1.1; can run almost entirely in parallel with the storage track and only needs to rendezvous at M2.7 (needs `BriefStore`, M1.11) and M2.5 (needs `MetadataStore`, M1.8/M1.9).
3. **Frontend track:** M4.4 needs only M1.1 and can proceed the entire time in parallel with all backend work — scaffolding, component library decisions (there are none, deliberately, per AD-14), and static views can be built against a mocked API and wired to real endpoints only once M4.1/M4.2 exist.
4. **Verification/scheduling track:** M3.1/M3.6 need only M1.1 and can be designed and stubbed early even though they don't wire up until M2.13 exists.
5. **Sync points** (where independent tracks must merge): M1.3 (domain models — everything downstream needs the enums/schemas settled first), M1.8+M1.9 (both `MetadataStore` implementations, needed by M2.5/M3.8/M3.12), M2.13 (service-layer facade — the single biggest fan-in point in the project, gating CLI chat, all of M3's automation/scheduling wiring, and all of M4).

## Verification

Each milestone in the PRD already states its own acceptance bar (§18) — this design doesn't change those, it just makes them reachable:

- **M1:** `mico track create/list` works end-to-end; hand-edit a brief externally and confirm reconciliation (M1.12); run `mico reindex` and diff resulting SQLite state; run the M1.19 in-memory-backend acceptance test.
- **M2:** run a full `refresh` against the mock agent with network disabled; confirm `mico chat` sustains multi-turn via `--resume`; assert every Stage 1 fixture in the corpus fails for the right reason; assert the agent process cannot read outside `workspace/`.
- **M3:** run a scheduled `autonomous` refresh unattended and inspect the resulting audit trail; point Stage 2 at a local model with zero code changes; attempt to export a disallowed Ledger field and confirm it's rejected; round-trip a snapshot.
- **M4:** drive every §5.1 operation through both CLI and web UI and diff results; run the §12.2 security checklist; confirm `ui/` contains no business logic (the AST layer-check from M1.1 should fail the build if it does).
