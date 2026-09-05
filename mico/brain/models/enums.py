"""Closed enums for the `mico` domain model (PRD §2: "All enums are closed sets.").

All enums are `enum.StrEnum` so they serialize as their plain string value in
JSON/YAML (frontmatter, API payloads, log lines) with no custom encoder.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "TrackType",
    "Priority",
    "TrackStatus",
    "AutomationMode",
    "VerifierStage1Result",
    "RevisionSource",
    "ApprovedBy",
    "EvidenceSourceType",
    "ValidationStatus",
    "RunOperation",
    "RunTrigger",
    "RunStatus",
    "RunOutcome",
    "ErrorClass",
    "LedgerSeverity",
    "LedgerType",
    "LedgerOrigin",
    "LedgerStatus",
    "ExportState",
    "ScheduleFrequency",
    "DayOfWeek",
    "ScheduleExecutionMode",
    "MisfirePolicy",
    "NotificationCategory",
]


class TrackType(StrEnum):
    DELIVERABLE = "deliverable"
    ONGOING = "ongoing"


class Priority(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class TrackStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class AutomationMode(StrEnum):
    """§5.8: per-Track, default `proposal`; `autonomous` requires Stage 2 configured."""

    PROPOSAL = "proposal"
    AUTONOMOUS = "autonomous"


class VerifierStage1Result(StrEnum):
    """Frontmatter `verifier_stage1` (§2.2 example: `verifier_stage1: pass`)."""

    PASS = "pass"
    FAIL = "fail"


class RevisionSource(StrEnum):
    AGENT = "agent"
    USER_EDIT = "user_edit"
    IMPORT = "import"
    CONDENSATION = "condensation"


class ApprovedBy(StrEnum):
    HUMAN = "human"
    AUTONOMOUS = "autonomous"
    NA = "n/a"


class EvidenceSourceType(StrEnum):
    MANUAL = "manual"
    FILE = "file"
    URL = "url"


class ValidationStatus(StrEnum):
    OK = "ok"
    UNREACHABLE = "unreachable"
    UNVERIFIABLE = "unverifiable"
    UNCHECKED = "unchecked"


class RunOperation(StrEnum):
    """§5.1 Operation Set."""

    RECAP = "recap"
    DELTA = "delta"
    REFRESH = "refresh"
    CONDENSE = "condense"
    TASK = "task"
    EVIDENCE = "evidence"
    ARTIFACT = "artifact"
    CHAT = "chat"
    ASK = "ask"


class RunTrigger(StrEnum):
    CLI = "cli"
    WEB = "web"
    SCHEDULE = "schedule"
    SYSTEM = "system"


class RunStatus(StrEnum):
    """AD-11 Run state machine. `status` is where the Run is now; `outcome`
    (below) is how it ended -- the two are deliberately not conflated.

    Active: running_agent -> validating -> committing -> complete.
    Parked (durable across restart): awaiting_approval, awaiting_decision,
    suspended, timed_out.
    Terminal: complete, failed, abandoned, superseded.
    """

    RUNNING_AGENT = "running_agent"
    VALIDATING = "validating"
    COMMITTING = "committing"
    COMPLETE = "complete"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_DECISION = "awaiting_decision"
    SUSPENDED = "suspended"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"


class RunOutcome(StrEnum):
    """PRD §2.5 base set plus AD-13's consolidated additions
    (timed_out, conflict, depleted, superseded). `None` while a Run is
    still in flight is expressed by the field being `Optional`, not a
    member here.
    """

    SUCCESS = "success"
    STAGE1_REJECTED = "stage1_rejected"
    STAGE2_REJECTED = "stage2_rejected"
    AGENT_ERROR = "agent_error"
    NO_PROPOSAL = "no_proposal"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"
    TIMED_OUT = "timed_out"
    CONFLICT = "conflict"
    DEPLETED = "depleted"
    SUPERSEDED = "superseded"


class ErrorClass(StrEnum):
    """AD-09: classified by what makes the failure go away, not where it occurred."""

    TRANSIENT = "transient"
    DEPLETED = "depleted"
    BUDGET = "budget"
    CONFIG = "config"
    CONTENT = "content"
    FATAL = "fatal"


class LedgerSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LedgerType(StrEnum):
    BUG = "bug"
    FEATURE = "feature"
    REFACTOR = "refactor"
    HEALTH = "health"


class LedgerOrigin(StrEnum):
    USER = "user"
    SYSTEM = "system"


class LedgerStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    WONT_FIX = "wont_fix"


class ExportState(StrEnum):
    LOCAL = "local"
    EXPORTED = "exported"


class ScheduleFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    INTERVAL = "interval"


class DayOfWeek(StrEnum):
    """§11.1: `days_of_week`, e.g. `MO`/`WE`/`FR`."""

    MO = "MO"
    TU = "TU"
    WE = "WE"
    TH = "TH"
    FR = "FR"
    SA = "SA"
    SU = "SU"


class ScheduleExecutionMode(StrEnum):
    EMBEDDED = "embedded"
    EXTERNAL = "external"


class MisfirePolicy(StrEnum):
    COALESCE = "coalesce"
    SKIP = "skip"
    RUN_ALL = "run_all"


class NotificationCategory(StrEnum):
    """AD-12: actionable (derived from parked Run state, not dismissible) vs.
    informational (event-emitted, dismissible)."""

    ACTIONABLE = "actionable"
    INFORMATIONAL = "informational"
