# Product Requirement Document (PRD): Mission Control (`mico`)

**Document Status:** Draft for HLD
**Version:** 3.0.0 (supersedes 2.0.0)
**Target Architecture:** Local-First, Single-User, On-Premise CLI & Web Application
**Repository Model:** Open Source (git clone / local execution)

---

## Change Log from v2.0.0

v3.0.0 resolves the integration architecture, which changes the system description materially.

**The central change:** `mico` no longer contains a Worker Agent. Claude Code is the Worker. `mico` is a **schema owner, orchestrator, validator, and store** wrapped around an external agent it does not control. §1 and §5 are rewritten accordingly; readers familiar with v1/v2 should re-read those two sections rather than skimming.

Resolved since v2.0.0: integration model (§4), Claude Code invocation and CLI interactivity (§5), OPEN-3 (§5.6), provider split (§5.2), General Workspace (§6), agent scoping and filesystem boundary (§4.4), schema delivery (§5.5), evidence integrity approach (§7), audit trail (§9).

Tags used: **[RESOLVED]**, **[OPEN-n]** (see §16), **[DEFERRED]**.

---

## 1. System Overview

### 1.1 What `mico` Is

Mission Control (`mico`) is an open-source, local-first operational workspace for software engineering managers, handling dual-track work streams:

1. **Deliverable Tracks** — discrete work with an explicit deadline (manager presentations, sprint prep, performance reviews).
2. **Ongoing Tracks** — continuous knowledge threads (architecture strategy, team performance, cross-dept dependencies) where a **State Brief** holds current ground truth, linked to evidence rather than containing it.

**`mico` does not talk to GitHub, Slack, or Jira. It does not hold credentials for them. It does not implement agents.**

It defines a schema, constructs prompts, invokes Claude Code, validates what comes back, and commits or rejects it. Claude Code — already installed and already authorised against the user's tools — does the reading and the writing.

The system's four responsibilities:

| Responsibility | Meaning |
|---|---|
| **Schema owner** | Defines the State Brief format and the sidecar contract. The only authority on what valid state looks like. |
| **Orchestrator** | Decides what runs, when, against which track, with which scope and permissions. |
| **Validator** | Gates every proposed change. Deterministic checks always; optional LLM grounding checks. |
| **Store** | Owns briefs, revisions, evidence index, run history, ledger, schedules. |

### 1.2 Consequences of This Model

Stated plainly, because they constrain the HLD:

- **`mico` cannot see what the agent read.** It validates the artifact, not the process. Evidence integrity is bounded (§7).
- **The trust boundary is a file**, not a transcript. `mico` never parses agent conversational output as state.
- **Agent behaviour is non-deterministic.** Validation must assume malformed or absent output as a normal case, not an error case.
- **Two provider shapes exist** (§5.2), split by role: agentic for authoring, direct API for verification.

### 1.3 Non-Goals (v1.0)

- Multi-user, team, or shared-workspace functionality.
- Hosted or remote deployment.
- Direct integrations with GitHub, Slack, Jira, email, or calendar. **[DEFERRED]** — deliberately, to avoid holding third-party credentials in v1.
- Mobile clients; real-time collaborative editing; semantic/vector search.
- Any telemetry, analytics, or crash reporting.

### 1.4 Glossary

| Term | Definition |
|---|---|
| **Track** | Top-level unit of work. Type `deliverable` or `ongoing`. Owns exactly one State Brief. |
| **State Brief** | The structured Markdown document holding current ground truth for a Track. Overwritten wholesale; never appended to. |
| **Brief Revision** | Immutable historical version of a State Brief. |
| **Evidence Pointer** | Reference from a brief statement to a source. Never contains source content. |
| **Proposal** | A `.proposed.md` sidecar file written by the agent, pending validation. |
| **Mutation** | An accepted Proposal, committed as a new Revision. |
| **Agent** | Claude Code, invoked as a subprocess. Authors briefs. External to `mico`. |
| **Verifier** | `mico`'s validation pipeline. Stage 1 deterministic (mandatory), Stage 2 LLM grounding (optional). |
| **Run** | One invocation of an operation. Always recorded. |
| **General Workspace** | UI affordance covering shared knowledge and cross-track queries. Not a Track (§6). |
| **Ledger** | Local issue table. |

### 1.5 Runtime Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Local Machine                             │
│                                                                  │
│  ┌────────────────────────┐     ┌─────────────────────────────┐  │
│  │   CLI (`mico`)         │     │  Local Web UI (127.0.0.1)   │  │
│  └───────────┬────────────┘     └──────────────┬──────────────┘  │
│              └──────────────┬──────────────────┘                 │
│                             ▼                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              Orchestrator (mico/logic/)                     │  │
│  │   Prompt assembly · Run lifecycle · Scheduler · Validator   │  │
│  └───────┬─────────────────────────────────────┬──────────────┘  │
│          │ subprocess                          │ HTTPS           │
│          ▼                                     ▼                 │
│  ┌──────────────────┐              ┌────────────────────────┐    │
│  │  Claude Code     │              │  Verifier Provider     │    │
│  │  (agent/Worker)  │              │  (any LLM, Stage 2)    │    │
│  │  holds GitHub/   │              │  optional, swappable,  │    │
│  │  Slack/Jira auth │              │  may be local model    │    │
│  └────────┬─────────┘              └────────────────────────┘    │
│           │ reads/writes files only                              │
│           ▼                                                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              workspace/  (agent-visible)                   │  │
│  │              briefs · proposals · knowledge                │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │   mico.db · runs/ · config.toml · .env  (agent-invisible)  │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Model

All enums are closed sets.

### 2.1 Track

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv7 | Immutable. |
| `slug` | string | `[a-z0-9-]{3,48}`, unique. CLI handle and directory name. |
| `title` | string | ≤ 120 chars. |
| `type` | enum | `deliverable` \| `ongoing` |
| `priority` | enum | `p0` \| `p1` \| `p2` \| `p3` |
| `status` | enum | `active` \| `paused` \| `archived` |
| `starred` | bool | UI affordance only; no logic attached. |
| `category` | string \| null | Free text. Filtering and contradiction-candidate selection (§8.3). |
| `due_at` | datetime \| null | Required iff `type = deliverable`. |
| `created_at` / `updated_at` | datetime | UTC, ISO 8601. |
| `last_verified_at` | datetime \| null | Last accepted Mutation. Drives staleness. |
| `refresh_interval_hint` | duration \| null | Default 7d for `ongoing`, null for `deliverable`. |
| `automation_mode` | enum | `proposal` \| `autonomous` (§5.8). |

**Track relationships — [DEFERRED].** No formal links in v1. A brief may name another track's slug in prose; the system attaches no meaning.

**Deliverable after `due_at` — [RESOLVED].** Nothing automatic. Renders as overdue; user archives manually. Auto-archiving incomplete obligations is the opposite of this tool's purpose.

### 2.2 State Brief

Markdown with YAML frontmatter and a fixed, ordered set of H2 sections. Sections may be empty but must be present and in order.

```markdown
---
track_slug: architecture-migration
revision: 47
generated_at: 2026-09-02T10:15:00Z
generated_by: claude-code
run_id: 0192f3a1-...
verifier_stage1: pass
verifier_stage2_score: 0.91          # null if Stage 2 disabled
word_count: 312
unattributed_statements: 2           # §7.3
change_summary: "SecOps sign-off received; v2 endpoint unblocked"
---

## Ground Truth
Declarative statements of current state. Each SHOULD carry an evidence pointer.

## Blockers
Active impediments. What is blocked, on whom/what, since when.

## Open Threads
Unresolved questions and in-flight decisions.

## Recent Changes
What moved since the previous revision.

## Notes
Free-form. Exempt from Stage 2 grounding checks; still subject to length limits.
```

**Size limits — [RESOLVED].** Measured in words of body text, excluding frontmatter and pointer syntax.

- **Soft limit 500 words** — flags for condensation at next health audit.
- **Hard limit 750 words** — Stage 1 rejection, before any LLM call.
- Per-Track configurable; above are defaults.
- Counted by one shared utility used identically by prompt assembly, Stage 1, and the health audit. Divergent counting between components is a latent bug class.

`format_version` in frontmatter supports migration.

### 2.3 Brief Revision

Every accepted Mutation writes an immutable Revision. Required to support delta reports (§5.1) and the audit trail (§9), which are impossible under pure overwrite.

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv7 | |
| `track_id` | UUID | |
| `revision` | int | Monotonic per Track from 1. |
| `content` | text | Full Markdown body. |
| `content_hash` | string | SHA-256. External-edit detection (§3.2). |
| `created_at` | datetime | |
| `source` | enum | `agent` \| `user_edit` \| `import` \| `condensation` |
| `run_id` | UUID \| null | |
| `verifier_stage2_score` | float \| null | |
| `approved_by` | enum | `human` \| `autonomous` \| `n/a` |
| `change_summary` | string | ≤ 140 chars. |

**Retention — [RESOLVED].** All revisions for 90 days; then one per week indefinitely; always the first and most recent 20. Configurable. `mico track history <slug> --prune` for manual cleanup.

### 2.4 Evidence Pointer

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv7 | |
| `track_id` | UUID | |
| `uri` | string | See schemes below. |
| `label` | string | Human-readable. |
| `source_type` | enum | `manual` \| `file` \| `url` |
| `first_seen_at` | datetime | |
| `last_validated_at` | datetime \| null | |
| `validation_status` | enum | `ok` \| `unreachable` \| `unverifiable` \| `unchecked` |
| `consecutive_failures` | int | Drives dead-reference flagging (§8.4). |

**In-brief syntax:** `[^ev:<short_id>]`, resolved against the evidence index at render time.

**URI schemes (v1.0):**

| Scheme | Example | `mico` validation |
|---|---|---|
| `manual:` | `manual:standup-2026-09-01` | Never validated. Always `ok`. |
| `file:` | `file:///Users/me/notes/q3.md` | Filesystem stat. |
| `https:` | `https://github.com/org/repo/pull/42` | Well-formedness only. See below. |

**`mico` does not dereference `https:` pointers.** It has no credentials for private GitHub, Slack, or Jira URLs; a HEAD request against them would return 401/404 and generate false dead-reference alarms. Status `unverifiable` exists for exactly this case. Only public, unauthenticated URLs are reachability-checked, and only on an opt-in setting. **This is a direct consequence of the no-credentials model and must not be designed around in the HLD.**

**Snippet caching — [RESOLVED, resolves OPEN-6 from v2].** `mico` does not fetch or cache source content in v1. The agent may include a short quoted excerpt inline in the brief; §7.3 bounds how much.

### 2.5 Run

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv7 | |
| `track_id` | UUID \| null | Null for `ask` and system operations. |
| `operation` | enum | §5.1. |
| `trigger` | enum | `cli` \| `web` \| `schedule` \| `system` |
| `started_at` / `ended_at` | datetime | |
| `outcome` | enum | `success` \| `stage1_rejected` \| `stage2_rejected` \| `agent_error` \| `no_proposal` \| `cancelled` \| `internal_error` |
| `agent_session_id` | string \| null | Claude Code session ID, for `--resume`. |
| `attempt_count` | int | Agent↔validator round trips. |
| `stage1_failures` | json \| null | Structured failure reasons. |
| `stage2_score` | float \| null | |
| `automation_mode` | enum | Mode in effect for this Run. |
| `log_ref` | string \| null | §12.3. |

Token counts and cost are recorded when the agent reports them, best-effort. Cost is not a v1 control surface.

### 2.6 Ledger Entry

| Field | Type | Notes |
|---|---|---|
| `id` | int | Sequential, referenced as `#104`. |
| `created_at` / `updated_at` | datetime | |
| `component` | string | e.g. `logic.validator`, `brain.storage`. |
| `severity` | enum | `low` \| `medium` \| `high` \| `critical` |
| `type` | enum | `bug` \| `feature` \| `refactor` \| `health` |
| `origin` | enum | `user` \| `system` |
| `title` / `description` | string / text | |
| `status` | enum | `open` \| `acknowledged` \| `resolved` \| `wont_fix` |
| `run_id` | UUID \| null | |
| `export_state` | enum | `local` \| `exported`, plus `exported_url` |

---

## 3. Storage

### 3.1 Layout — [RESOLVED]

The split between agent-visible and agent-invisible is a **security boundary**, enforced by the filesystem and by process scoping (§4.4), not by agent instruction.

```
$MICO_HOME/                        # default ~/.mico
  workspace/                       # ← the ONLY thing an agent ever sees
    tracks/
      architecture-migration/
        brief.md                   # current State Brief
        .proposed.md               # transient sidecar (§4.2)
    knowledge/                     # shared context (§6.1)
  revisions/                       # compressed historical revisions
  mico.db                          # SQLite: all structured data
  runs/                            # Run logs
  exports/
  snapshots/
  config.toml
  .env                             # fallback credential store only
```

Run logs, the database, and credentials sit outside `workspace/` deliberately. Run logs in particular may contain full prompts; they must never enter an agent's context.

`workspace/` is pure text with no database and no secrets, which makes it cleanly git-able (§9.3).

### 3.2 Single Source of Truth — [RESOLVED]

**For brief body content, the Markdown file on disk is authoritative. For everything else, SQLite is authoritative.**

- On read, `mico` compares the file's SHA-256 against the current Revision's `content_hash`.
- On mismatch, the file wins: new Revision with `source = user_edit`, `verifier_stage2_score = null`, `approved_by = n/a`, plus a `low` Ledger entry. User is informed at next interaction.
- Externally-edited briefs violating the §2.2 structure are accepted but flagged `structurally_invalid`. No agent Run may be started against a structurally invalid brief until `mico track repair <slug>` or manual fix.
- `mico reindex` rebuilds derivable SQLite state from files. **It cannot recover Ledger or Run history**, which exist only in SQLite — this makes the database backup-critical (§10).

### 3.3 Concurrency — [RESOLVED]

- **Single-writer.** Mutating operations take an exclusive lock on `$MICO_HOME/.lock` (`flock` / `msvcrt`). 30s timeout, then abort naming the holding PID and operation.
- Reads take no lock; SQLite in WAL mode.
- Per-Track logical locks prevent concurrent Runs on one Track. A second interactive Run is **rejected** (no job queue in v1); a scheduled Run is **skipped with a logged reason**.
- Different Tracks may run concurrently. This is why `.proposed.md` is per-Track (§4.2).

### 3.4 Schema Versioning — [RESOLVED]

`config.toml`, `mico.db`, and brief frontmatter each carry a version. Forward migrations only, run at startup after an automatic pre-migration snapshot. Restoring a snapshot from a newer schema than the running binary is refused explicitly.

---

## 4. The Agent Integration

**This section replaces §3 (Connectors) of v2.0.0 in its entirety.**

### 4.1 Model — [RESOLVED]

`mico` invokes **Claude Code** as a subprocess. Claude Code already holds the user's credentials for GitHub, Slack, Jira and whatever else the user has configured, via its own MCP servers and configuration. `mico` neither reads, stores, injects, nor is aware of those credentials.

This makes the entire third-party credential surface someone else's problem in v1 — the explicit goal.

**Prerequisite:** Claude Code must be installed and configured. `mico doctor` verifies the binary, version, and authentication, and fails with actionable messaging if absent.

### 4.2 The Sidecar Contract — [RESOLVED]

`mico` **never parses agent conversational output as state.** All state arrives through a file.

Flow:

1. `mico` writes `.proposed.md` into the track directory, pre-populated with the correct empty section structure (schema-by-example).
2. `mico` invokes the agent with a prompt containing the schema and the task, cwd set to the track directory.
3. The agent fills in `.proposed.md` using its ordinary file tools.
4. On completion, `mico` reads and validates the file (§7).
5. Accept → new Revision, `.proposed.md` deleted. Reject → retained for user inspection, marked in the Run record.

**Per-Track, not shared** — [RESOLVED]. Two reasons: concurrent Runs on different tracks would clobber a shared file (§3.3), and a crashed Run leaves the proposal exactly where it belongs, so `mico` knows on next start which track has an uncommitted proposal. Because cwd is the track directory, the agent only ever sees the bare filename.

**Orphan recovery:** on startup, `mico` scans for `.proposed.md` files without an active Run and surfaces them as pending, offering validate / discard / inspect. The lifecycle state machine is an HLD deliverable.

### 4.3 Invocation Modes — [RESOLVED]

All three surfaces use one mechanism: `claude -p` with `--output-format stream-json`, plus `--resume <session_id>` for multi-turn.

| Surface | Invocation | Notes |
|---|---|---|
| **CLI interactive** (`mico chat <slug>`) | `mico` owns the REPL; per turn, `claude -p --resume <sid>`; stream rendered via Rich | Session ID held in `mico` state, not a TTY. No hierarchy inversion needed. |
| **Web chat** | Identical invocation; stream relayed to browser | Same code path, different renderer. |
| **Scheduled / batch** | Single `claude -p`, no resume, restricted tools | No human present; see §4.5. |

Each `-p` invocation is a batch turn: everything the agent needs must be in the prompt, in files it can read, or in tools it may call. The sidecar design satisfies this — briefs and knowledge are files.

**Session persistence:** `mico` stores `agent_session_id` on the Run. Sessions created programmatically are resumable by ID.

### 4.4 Scoping — [RESOLVED]

Two independent enforcement mechanisms; neither depends on the agent behaving well.

| Operation class | cwd | Additional access | Tools |
|---|---|---|---|
| Track-scoped (`refresh`, `condense`, `chat`) | `workspace/tracks/<slug>/` | `workspace/knowledge/` read-only | Read + write within cwd, plus configured MCP sources |
| Cross-track (`ask`) | `workspace/` | — | **Read-only allowlist**; no file writes |

The agent is never given `$MICO_HOME` as cwd. It cannot reach `runs/`, `mico.db`, `config.toml`, or `.env`.

### 4.5 Permissions — [RESOLVED]

Scheduled Runs have no human to answer approval prompts. They run with an explicit `--allowedTools` allowlist, configured per install and defaulting to read-only sources plus write access limited to the track directory.

`--dangerously-skip-permissions` is **never** used by `mico` and is not exposed as a configuration option.

This is the enforcement mechanism for the "read-only needs" intent, which is otherwise merely an instruction.

### 4.6 Schema Delivery — [RESOLVED]

Two mechanisms, deliberately redundant:

- **(A) System prompt** — `mico` passes the brief schema via `--append-system-prompt` on every invocation. Self-contained, versioned with `mico`, independent of the user's Claude Code configuration.
- **(D) Pre-structured file** — `.proposed.md` is written with the correct empty shape before the agent starts.

**Explicitly rejected:** a `mico`-managed `CLAUDE.md` — it collides with the user's own, and being user-editable it is an unvalidated input path into the prompt. **A Claude Code Skill** — cleaner but adds an install dependency and access-path assumptions. Reconsider post-v1.

The schema does **not** live in `workspace/knowledge/`. That is user content; the schema is `mico`'s contract with itself, and mixing them means a user editing their presentation guidelines could break brief parsing.

### 4.7 Programmatic Invocation Authorisation — [RESOLVED, was OPEN-3]

Guidance for products wrapping Claude Code points to running against an **API key** rather than a subscription, as the unambiguously supported path. `mico` is such a wrapper.

- `mico` requires `ANTHROPIC_API_KEY` for its invocations.
- This is one Anthropic credential. The no-third-party-credentials property (§4.1) is unaffected.
- It also removes ambiguity about who pays for unattended scheduled Runs.
- **Verify against current Anthropic terms before public release.** This is a licensing question, not a technical one.

### 4.8 Future Direct Integrations — [DEFERRED]

Direct connectors are explicitly post-v1. Should they arrive, they enter as an ingestion source feeding the same sidecar and validation pipeline, not as a parallel path. Nothing in v1 should preclude this, but nothing in v1 should build for it.

---

## 5. Operations & Agent Orchestration

### 5.1 Operation Set

| Operation | Description | Agent? | Writes brief? | Validated? |
|---|---|---|---|---|
| `recap` | Summary from current brief | No | No | n/a |
| `delta` | Diff between Revisions or since a timestamp | No | No | n/a |
| `refresh` | Gather updates, propose new brief | Yes | Yes | Stage 1 + 2 |
| `condense` | Prune to word budget | Yes | Yes | Stage 1 + 2 (loss rubric) |
| `task` | Draft action items, comms, blocker analysis | Yes | No | Stage 1 shape only |
| `evidence` | List and check pointers | No | No | n/a |
| `artifact` | Export document, table, outline | Yes | No | Stage 1 shape only |
| `chat` | Interactive session | Yes | Optionally | Full, if it proposes |
| `ask` | Cross-track query (§6.2) | Yes | No | n/a |

`recap` and `delta` are computed locally from stored state — no agent, no network, work offline.

### 5.2 Provider Shapes — [RESOLVED]

Two shapes, split by role, not by surface. The distinction is capability, not billing.

| | Agentic Provider | Verification Provider |
|---|---|---|
| **Implementation** | Claude Code subprocess | Direct HTTP `/v1/messages` or equivalent |
| **Used for** | All brief authoring and evidence gathering | Stage 2 grounding only |
| **Characteristics** | Tool use, MCP, multi-turn, filesystem, holds user's third-party auth | One stateless call, no tools, no memory |
| **Swappable** | No — Claude-specific by definition | **Yes — any provider** |
| **Optional** | No | Yes (§7.2) |

The Verifier's fixed input/output contract and absence of tool use mean it can run against a cheaper model tier or a local model (Ollama or equivalent) at effectively zero marginal cost. The `Verifier` ABC must be provider-agnostic from day one even though one implementation ships. **[Resolves OPEN-1.]**

### 5.3 Prompt Assembly

Every agent invocation is assembled from versioned templates:

1. Schema and output contract (`--append-system-prompt`)
2. Operation instruction
3. Current brief content
4. Relevant `knowledge/` context
5. Track metadata and time window

Template IDs are recorded on the Run. No prompt strings inline in engine code.

### 5.4 Interactive Session State — [RESOLVED]

- A `chat` session is a conversation held by Claude Code, addressed by `agent_session_id`. `mico` holds the ID, not the transcript.
- Sessions are **not persisted by `mico` by default.** `mico chat <slug> --save` writes a transcript to the Run log.
- A chat session may write `.proposed.md`, which enters the standard validation pipeline. **Chat cannot bypass validation.**

### 5.5 Artifact Export

Outputs to `$MICO_HOME/exports/` or a user-specified path. Every artifact carries a footer: machine-generated, source Track, Revision number, timestamp.

### 5.6 Retry & Termination — [RESOLVED]

- **Max 2 retries** (3 agent attempts), configurable.
- Retries pass structured Stage 1 failure reasons or Stage 2 scores, never raw reasoning text.
- **On final failure:** brief unchanged, Run recorded with the rejection outcome, `.proposed.md` retained, `health` Ledger entry at `medium`. In `proposal` mode the user sees the rejected draft and reasons, and may force-apply with `--force` (recorded as `source = user_edit`, `approved_by = human`).
- 3 consecutive rejections on one Track → escalate to `high`, pause that Track's schedules until acknowledged. Silent repeated failure is worse than a stopped schedule.

### 5.7 Agent Failure Modes

Distinct from validation failure and handled separately:

| Failure | Outcome | Response |
|---|---|---|
| Claude Code not installed / not authenticated | `agent_error` | Actionable message; `mico doctor` |
| Agent exits without writing `.proposed.md` | `no_proposal` | Recorded; not a validation failure |
| Agent reports missing credentials for a source | `success` with warning | Surfaced loudly (§7.4) |
| Agent times out | `agent_error` | Configurable timeout, default 10 min |
| Malformed `stream-json` | `agent_error` | Log raw output for debugging |

### 5.8 Automation Modes — [RESOLVED]

- `automation_mode` is **per-Track**, default `proposal`. A global default may be configured; each Track carries its own value.
- Promotion to `autonomous` is a **deliberate manual action**. No automatic promotion based on score history — a system that quietly grants itself autonomy cannot be reasoned about.
- **`autonomous` requires Stage 2 to be configured.** Stage 1 alone catches structural failure, not fabrication. Unattended writes without grounding checks are not acceptable; a human reading a diff in `proposal` mode is.
- Every autonomous Mutation writes a Run and a Revision with `approved_by = autonomous`. Surfaced via the audit trail (§9).
- **Force-downgrade to `proposal`** after 3 consecutive rejections, with a Ledger entry.

---

## 6. General Workspace

**[New in v3.]** Two distinct capabilities, presented together in the UI, implemented separately. **Neither is a Track** — a Track owns a brief and a verification lifecycle, and neither of these does. Modelling them as Tracks would mean special-casing a `general` type through §2, §7, and §8.

### 6.1 Shared Knowledge

Presentation guidelines, house style, reusable instructions, general-purpose skills.

- Lives at `workspace/knowledge/`, plain files, user-owned.
- Injected into every agent invocation as read-only context (§4.4).
- No brief, no revisions, no verifier, no staleness index.
- Editable directly on disk or through the UI.
- Size-bounded with a warning past a threshold, since it enters every prompt.

### 6.2 Cross-Track Queries (`mico ask`)

"What's blocked right now." "Summarise all track statuses." "Which deliverables are at risk this week."

- Read-only agent operation with cwd `workspace/`, read-only tool allowlist.
- Reads all briefs plus `knowledge/`.
- **Produces no persistent state.** The answer is derived and stale the moment it is computed.
- Recorded as a Run with `track_id = null`. Output may be exported as an artifact.

### 6.3 UI Presentation

The General Workspace appears alongside Tracks in navigation and may look track-like. It has a distinct visual treatment and offers no brief, no refresh, no automation controls.

---

## 7. Validation

### 7.1 Stage 1 — Deterministic (mandatory, no LLM)

**The only mandatory gate in v1.** Runs on every proposal. Costs nothing, runs in milliseconds, catches the structural failure modes.

Checks:

1. File exists and is readable
2. YAML frontmatter parses; required fields present; `format_version` supported
3. All required H2 sections present, correctly ordered, no unknown sections
4. Word count ≤ hard limit
5. All `[^ev:...]` references resolve to evidence index entries
6. All evidence URIs well-formed and use a supported scheme
7. No unattributed bulk quotation — no fenced block or quoted passage above a threshold without an accompanying pointer
8. `change_summary` present, ≤ 140 chars
9. `track_slug` matches the target Track

Failures are structured, machine-readable, and fed back on retry. The exhaustive check list with exact thresholds is an HLD deliverable.

### 7.2 Stage 2 — LLM Grounding (optional)

- Single stateless call. Inputs: prior brief, proposed brief, and any evidence excerpts present in the proposal. Output: score 0.0–1.0 plus structured reasons.
- **Never sees agent reasoning or transcript.** The black-box property is now structural rather than enforced — `mico` only has the file. This is a benefit of the sidecar design.
- Default threshold 0.85, configurable.
- Different rubric for `condense`: checks information loss and unwarranted new claims, not source consistency.
- **Optional in v1.** Disabled → `proposal` mode still works; `autonomous` is unavailable (§5.8).

**[OPEN-2] Score stability.** A single call compared against a fixed threshold is nondeterministic near the boundary. Interim: temperature 0, persist every raw score, examine the distribution before committing to best-of-N or a human-review band.

### 7.3 Evidence Integrity — [RESOLVED: optimistic]

**`mico` cannot see what the agent read.** It validates the artifact, not the process. Provenance integrity is therefore an **agent-compliance property, not a system guarantee** — and the PRD says so rather than implying it is airtight.

v1 approach: **instruct, validate shape, fail loudly.**

- The schema instructs the agent to attach a pointer to every Ground Truth statement.
- Stage 1 validates that pointers are well-formed and resolve within the evidence index.
- `mico` does **not** verify that a pointer supports the claim it is attached to, nor that the agent actually read it.

**Reject vs. flag — [RESOLVED].** Malformed pointers are **rejected**; a broken URI is unambiguously wrong. Missing pointers are **flagged, not rejected**: a Ground Truth statement may legitimately come from the manager's own judgment or a hallway conversation, and hard-rejecting those trains people to fabricate pointers to satisfy the validator — precisely the failure mode being guarded against. `unattributed_statements` is recorded in frontmatter, surfaced in the UI, and escalated by the health audit if the ratio climbs.

**Post-v1 options, recorded not built:** an `.evidence.json` manifest the agent must populate, validated against brief pointers (catches fabricated references); or reconciling claimed pointers against actual tool calls parsed from `stream-json` (independent of agent self-report, but reintroduces transcript parsing).

### 7.4 Loud Failures

Never silent, always surfaced in CLI output, UI, and the Ledger:

- Malformed or unresolvable evidence pointer
- Agent reports missing credentials for a source
- Agent reports it could not access a requested source
- `.proposed.md` missing after a Run
- Sidecar fails schema validation
- Stage 2 configured but provider unreachable

---

## 8. System Health Audit

### 8.1 Execution

Scheduled daily at 03:00 local by default, plus `mico health`. Writes `health` Ledger entries with `origin = system`. **Advisory only** — never mutates a brief, never deletes a pointer. Findings matching an existing open entry update it rather than duplicating.

### 8.2 Staleness Index

```
staleness = (now - last_verified_at) / refresh_interval_hint
```

Flagged at `> 1.5` (`low`) and `> 3.0` (`medium`). Tracks with neither `refresh_interval_hint` nor `due_at` are exempt. For Deliverables, proximity to `due_at` raises severity one level.

### 8.3 Contradiction Detection

All-pairs comparison is O(N²) LLM calls and unbounded.

- **Within-Track first** — `## Ground Truth` versus `## Blockers` in one brief. One call per Track, catches the common case.
- **Cross-Track candidate-filtered** — only pairs sharing a `category` or exceeding a lexical-overlap threshold. Hard cap per audit run, default 10.
- Findings quote both slugs and the conflicting statements verbatim.

### 8.4 Dead References

**Flags. Never purges.** Automatic deletion of provenance is irreversible from the user's perspective.

- Only `file:` and opt-in public `https:` pointers are checked. `manual:` and authenticated URLs are `unverifiable` and exempt (§2.4).
- 3 consecutive failures → `low` Ledger entry. Dead ratio > 25% on a Track → `medium`.
- `mico evidence prune <slug>` deletes, interactively, on explicit command only.

### 8.5 Bloat

Tracks over the soft limit are flagged and offered a `condense` Run — automatic in `autonomous` mode, proposed otherwise.

### 8.6 Unattributed Statements

Rising `unattributed_statements` ratio across revisions → `low` Ledger entry. A signal that the agent is drifting from the evidence discipline, worth surfacing before it compounds.

---

## 9. Audit Trail

**[New in v3.]** Motivated by **trust calibration, not compliance.** In `autonomous` mode the agent rewrites ground truth unattended. When the brief reads differently than the user remembers, "what changed, why, and on what evidence" is the difference between a tool they trust and one they second-guess.

### 9.1 No New Mechanism — [RESOLVED]

Brief Revisions (§2.3) already record what changed; Runs (§2.5) record why and by what. The audit trail is a **view joining them**, not a subsystem. Nothing additional is written.

### 9.2 Presentation

`mico audit [--since <ts>] [--track <slug>] [--autonomous-only]` and an equivalent UI panel. Per entry:

- Timestamp, Track, trigger, automation mode
- `change_summary` and full diff against the prior Revision
- Evidence pointers added or removed
- Stage 1 result; Stage 2 score if present
- `approved_by` — human, autonomous, or n/a

Retention rides on existing policies: Revisions per §2.3, Runs per §12.3. No third retention policy.

### 9.3 Git — [RESOLVED]

**`mico` does not implement version control and never shells out to git.**

Because `workspace/` is pure text with no database and no secrets (§3.1), it is cleanly git-able. `mico init --git` initialises it as a repository and commits on each accepted Mutation. Users who want blame, bisect, and branches get real git; users who don't get the SQLite-backed view. **`mico`'s own history is authoritative either way** — git is never load-bearing, and disabling it loses nothing.

---

## 10. Snapshots, Backup & Restore

- `mico snapshot create [--out <path>] [--encrypt]` — briefs, revisions, evidence index, Ledger, Run metadata, schedules, `knowledge/`, non-secret config, plus a manifest with `schema_version`.
- **Never included:** credentials, `.env`, keyring material, Run logs, `agent_session_id` values.
- `mico snapshot restore <path> --mode replace|merge` — `replace` is default and wipes existing state after a mandatory automatic pre-restore snapshot. `merge` imports Tracks whose slugs don't exist and refuses on collision, listing conflicts.
- Restore from a newer `schema_version` is refused (§3.4).
- Restore re-prompts for credentials.

**[OPEN-4] Snapshot encryption.** Even without credentials, brief content is highly sensitive and snapshots are intended for private Git sync. Recommendation: ship `--encrypt` opt-in.

---

## 11. Scheduling

### 11.1 Modes

- **Embedded** — an internal asyncio scheduling loop inside the local web server; active only while it runs. No third-party scheduler dependency (AD-15).
- **External** — `mico schedule export --format crontab|systemd|launchd|taskscheduler` emits definitions invoking the CLI.
- Each schedule carries `execution_mode` of `embedded` or `external`. The embedded scheduler skips `external` schedules and logs it. `mico schedule doctor` detects likely double-scheduling. This closes the dual-writer hazard alongside §3.3.

**Schedules are stored as structured fields, not cron strings** (AD-15):

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv7 | |
| `track_id` | UUID \| null | Null for global schedules (health audit). |
| `operation` | enum | §5.1. |
| `frequency` | enum | `daily` \| `weekly` \| `interval` |
| `time_of_day` | time \| null | For `daily` and `weekly`. |
| `days_of_week` | list \| null | For `weekly`. |
| `interval_hours` | int \| null | For `interval`. |
| `timezone` | string | IANA name; resolved via stdlib `zoneinfo`. |
| `execution_mode` | enum | `embedded` \| `external` |
| `misfire_policy` | enum | `coalesce` \| `skip` \| `run_all`. Default `coalesce` (§11.2). |
| `enabled` | bool | |
| `suspended_until` | datetime \| null | Set by Depleted-class failures (AD-09). |

**Resolution is minute-level.** A job firing at 02:15 rather than 02:00 is operationally acceptable, which is what removes the need for a cron library.

**Crontab export is formatting, not parsing** — structured fields render to `0 8 * * 1,3,5` in one direction only. Arbitrary cron expressions cannot be entered in v1; schedules are built through the CLI or UI. A restricted cron-subset parser is an additive change behind the `NextFireCalculator` interface if demand appears.

### 11.2 Missed Runs

Default **coalesce**: at most one catch-up Run per schedule regardless of misses, if the most recent miss is within `misfire_grace` (default 12h). Older misses logged and dropped. Configurable to `skip` or `run_all`.

### 11.3 Event Triggers — [DEFERRED]

No event bus in v1; only time triggers. Connector webhooks would require an inbound listener, conflicting with the localhost-only posture (§12.2).

### 11.4 Platform Support

- **Tier 1 (CI-tested):** macOS, Linux.
- **Tier 2 (best-effort):** Windows — CLI and web UI functional, Task Scheduler export, `msvcrt` locking. Known gaps documented rather than silently broken.

---

## 12. Security & Privacy

### 12.1 Credentials

- **Third-party (GitHub, Slack, Jira):** `mico` holds none. They live in Claude Code's configuration. **This is the single largest security simplification in v1.**
- **`ANTHROPIC_API_KEY`:** required for agent invocation (§4.7).
- **Verification provider key:** optional; may be absent entirely if using a local model.
- **Storage:** OS keyring by default; `.env` at mode `0600` as fallback with a first-run warning. Gitignored in the shipped template.
- A pre-write scrubber redacts key-shaped strings from all log output.

**Residual risk, stated plainly:** `mico` invokes an agent that holds write-capable credentials for the user's tools. The mitigations are the `--allowedTools` allowlist (§4.5), directory scoping (§4.4), and the prohibition on `--dangerously-skip-permissions`. This is a smaller surface than `mico` holding those credentials itself, but it is not zero.

### 12.2 Local Web Server

- Binds `127.0.0.1` only. Any other interface requires an explicit flag plus typed confirmation and prints a warning.
- Random session token per server start, embedded in the launch URL; required on all API routes.
- CSRF protection on state-changing routes; `Origin`/`Host` validation.
- Restrictive CSP, no third-party assets, frontend fully vendored, no CORS allowances.

### 12.3 Run Logs

- `$MICO_HOME/runs/<date>/<run_id>.jsonl`, mode `0600`, **outside `workspace/`** and therefore invisible to the agent.
- Contain: template IDs and rendered variables, invocation flags, session ID, timings, Stage 1 failures, Stage 2 scores, errors.
- **Full prompt and agent output stored only at `log_level = debug`** (off by default) — prompts contain the full brief and evidence.
- Retention 30 days, then purged.

### 12.4 Issue Export — [OPEN-5, highest-risk item]

Exporting Ledger entries to a **public** GitHub repository. Non-negotiable requirements regardless of how the open question resolves:

1. Always manual, per-entry, never batched, never scheduled, never automatic.
2. The user is shown the **exact final payload** and must confirm. No trust-the-sanitiser path exists.
3. Default-deny allowlist: `component`, `severity`, `type`, `mico_version`, `python_version`, `os`, stack trace. Free-text `title` and `description` only after user editing in the confirmation step.
4. **Never exported under any configuration:** track slugs, titles, brief content, evidence URIs, file paths, hostnames, usernames, prompt text, session IDs.
5. Stack traces path-scrubbed (home directory → `~`) before display.
6. `export_state` and `exported_url` recorded locally.

Open: whether to add a regex/LLM detection pass over user-edited text. The allowlist plus mandatory human review is the actual control; detection is a warning layer.

---

## 13. User Interfaces

### 13.1 Parity

Every operation in §5.1 is reachable from CLI and web. The web API is a thin binding over the same service layer the CLI calls. **No logic may live in `ui/`.**

### 13.2 Web UI Views

1. **Overview Dashboard** — urgent flags, pending proposals, open health findings, recent Runs, rapid switcher, global search (Cmd/Ctrl+K).
2. **Track Grid/List** — sort/filter by priority, staleness, star, category, type, last update.
3. **Interactive Workspace** — dual pane. Left: State Brief with inline pointers, revision selector, delta view. Right: **live Claude Code chat window** streaming from the same invocation the CLI uses.
4. **General Workspace** — knowledge editor plus `ask` console (§6).
5. **Administrative Hub** — Anthropic and verification credentials, Claude Code health check, schedules with mode indicator, snapshots, Ledger with the export confirmation flow, audit trail viewer.
6. **Track Summary Card** — star, slug/title, priority badge, type badge, last updated, one-line change summary, 2–3 line Ground Truth preview, staleness indicator, action triggers.

### 13.3 Error & Failure UX

Every failure surfaces: what failed, why, what the system did or did not do to state, and the next action. Validation rejections show structured reasons and the retained `.proposed.md`. Agent failures (§5.7) are distinguished from validation failures — conflating them makes debugging impossible.

---

## 14. Non-Functional Requirements

| Dimension | Target |
|---|---|
| Scale | ~50 active Tracks (~100 including archived), low thousands of Revisions. Human capacity is the bottleneck; most Tracks are idle or archived at any time. |
| CLI startup | < 300 ms to first output for non-agent commands |
| Local reads (`recap`, `delta`, list, search) | < 500 ms p95 |
| `refresh` end-to-end | Agent-latency dominant; `mico` overhead < 2 s |
| Health audit | < 5 min for ~50 active Tracks within the §8.3 call cap |
| Memory | < 250 MB RSS for the web server at idle, excluding agent subprocesses |
| Offline | All non-agent operations fully functional with no network |
| Agent timeout | 10 min default, configurable |

Cost is not a v1 control surface. Token counts are recorded for observability only.

---

## 15. Implementation Guidelines

1. **Strict layer separation**
   - `mico/brain/` — storage contracts, schemas, file I/O, evidence index, migrations
   - `mico/logic/` — orchestration, agent invocation, validators, scheduler, templates
   - `mico/ui/cli/` — Typer commands, Rich formatters
   - `mico/ui/web/` — FastAPI endpoints, static assets
   - CI-enforced via import-linter: `ui` may not import `brain` directly; `brain` may not import `logic` or `ui`.

2. **Component isolation via ABCs** — `Storage`, `AgentProvider`, `VerificationProvider`, `Scheduler`, `Validator`. Acceptance tests: swap the storage backend, and swap the verification provider for a local model, both with zero changes under `logic/` or `ui/`.

3. **Template-driven prompts** — versioned template files with IDs recorded on every Run. No prompt strings inline in engine code.

4. **Testability**
   - A **mock agent** that writes fixture `.proposed.md` files, enabling fully offline deterministic tests of the entire pipeline. This is the single most important test affordance in the system — the sidecar design makes it trivial.
   - A Stage 1 corpus of malformed proposals asserting each check fires correctly.
   - A Stage 2 corpus (faithful, hallucinated, lossy) asserting classification.
   - Golden-file tests for brief structure and rendering; migration round-trip tests.

5. **CLI-first** — core logic fully functional and tested via CLI before web bindings exist.

---

## 16. Open Decisions

| ID | Question | Blocks | Recommendation |
|---|---|---|---|
| OPEN-2 | Stage 2 score stabilisation near threshold (§7.2) | M3 | Temp 0; collect distribution before deciding |
| OPEN-4 | Optional snapshot encryption (§10) | M3 | Ship `--encrypt` opt-in |
| OPEN-5 | Detection layer above allowlist for issue export (§12.4) | M3 | Regex warning layer; allowlist + review is the real control |
| OPEN-9 | Search implementation and scope | M4 | SQLite FTS5 over briefs, evidence labels, Ledger; no vector search in v1 |
| OPEN-10 | Web UI freshness during background Runs | M4 | SSE from the local server, polling fallback |
| OPEN-11 | Manual Track ordering vs. sort precedence | M4 | Manual order as one selectable sort mode, persisted globally |
| OPEN-13 | License selection | M1 | Required before any public repo push |
| OPEN-14 | Minimum supported Claude Code version, and behaviour on version drift | M2 | Pin a minimum; `mico doctor` warns on mismatch |

**Resolved since v2.0.0:** OPEN-1 (verifier provider — any, configurable), OPEN-3 (API key, §4.7), OPEN-6 (no snippet caching in v1), OPEN-7 (cost not a v1 control surface), OPEN-8 (fail fast; local operations remain available offline), OPEN-12 (AD-14: `uv`/`pipx`, pre-built frontend assets committed, no Node at install).

**Note:** §14's scale targets were revised downward per AD-04 — ~50 active Tracks, ~100 including archived, low thousands of Revisions. The earlier figures were speculative and overstated real usage by roughly an order of magnitude.

---

## 17. Technical Stack

- **Language:** Python 3.11+
- **CLI:** Typer + Rich
- **Web:** FastAPI backend; local SPA (React), pre-built vendored assets
- **Validation:** Pydantic v2
- **Storage:** Markdown briefs + SQLite (WAL, FTS5)
- **Agent:** Claude Code CLI via subprocess, `-p --output-format stream-json`
- **Verification:** pluggable — any HTTP LLM API or local model
- **Scheduling:** internal asyncio loop over structured schedules (no dependency) + exported OS schedules
- **Credentials:** `keyring`, `.env` fallback
- **Testing:** pytest, pytest-asyncio; layer rules enforced by an internal AST script (AD-14)

---

## 18. Milestones

**M1 — Core Interfaces & Storage**
ABCs. Hybrid storage, migrations, full schema. Locking. Reconciliation and `reindex`. `workspace/` boundary.
*Accepts when:* Tracks create; briefs hand-edited externally reconcile correctly; `reindex` reproduces SQLite state; the swap-storage-backend test passes. Resolves OPEN-13.

**M2 — Agent Integration & Validation**
Claude Code invocation across all three modes. Sidecar lifecycle and orphan recovery. Stage 1 complete. Mock agent and Stage 1 corpus. `mico doctor`.
*Accepts when:* a full `refresh` runs end-to-end against the mock agent offline; `mico chat` sustains a multi-turn session via `--resume`; every Stage 1 check has a failing fixture; scoping is verified by asserting the agent cannot read `$MICO_HOME` outside `workspace/`. Resolves OPEN-14.

**M3 — Automation, Health, Ledger & Audit**
Stage 2 with a pluggable provider. Scheduler both modes. Health audit. Ledger and export flow. Snapshots. Autonomous mode with force-downgrade. Audit trail view.
*Accepts when:* a scheduled autonomous refresh completes unattended with a correct audit trail; Stage 2 runs against a local model with no code change; the export flow demonstrably cannot emit a disallowed field; snapshot round-trip preserves all state. Resolves OPEN-2, OPEN-4, OPEN-5.

**M4 — Web UI & REST API**
FastAPI over the same service layer. Security posture per §12.2. All six views, including the live agent chat window.
*Accepts when:* every §5.1 operation is reachable from CLI and UI with identical results; the security checklist passes; no logic exists under `ui/`. Resolves OPEN-9 through OPEN-12.
