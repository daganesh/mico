"""Domain models (Pydantic v2) for `mico.brain` (task M1.3, PRD §2).

Single import surface for every downstream task: `from mico.brain.models
import Track, Run, ...`. Split into one module per entity/concern rather
than one file, but re-exported here so callers never need to know that.
"""

from __future__ import annotations

from mico.brain.models._uuid7 import uuid7
from mico.brain.models.brief import BriefFrontmatter, BriefRevision
from mico.brain.models.common import MicoModel
from mico.brain.models.enums import (
    ApprovedBy,
    AutomationMode,
    DayOfWeek,
    ErrorClass,
    EvidenceSourceType,
    ExportState,
    LedgerOrigin,
    LedgerSeverity,
    LedgerStatus,
    LedgerType,
    MisfirePolicy,
    NotificationCategory,
    Priority,
    RevisionSource,
    RunOperation,
    RunOutcome,
    RunStatus,
    RunTrigger,
    ScheduleExecutionMode,
    ScheduleFrequency,
    TrackStatus,
    TrackType,
    ValidationStatus,
    VerifierStage1Result,
)
from mico.brain.models.evidence import EvidencePointer
from mico.brain.models.ledger import LedgerEntry
from mico.brain.models.notification import Notification
from mico.brain.models.run import Run
from mico.brain.models.schedule import Schedule
from mico.brain.models.track import Track

__all__ = [
    "MicoModel",
    "uuid7",
    # Track
    "Track",
    "TrackType",
    "Priority",
    "TrackStatus",
    "AutomationMode",
    # Brief
    "BriefFrontmatter",
    "BriefRevision",
    "VerifierStage1Result",
    "RevisionSource",
    "ApprovedBy",
    # Evidence
    "EvidencePointer",
    "EvidenceSourceType",
    "ValidationStatus",
    # Run
    "Run",
    "RunOperation",
    "RunTrigger",
    "RunStatus",
    "RunOutcome",
    "ErrorClass",
    # Ledger
    "LedgerEntry",
    "LedgerSeverity",
    "LedgerType",
    "LedgerOrigin",
    "LedgerStatus",
    "ExportState",
    # Schedule
    "Schedule",
    "ScheduleFrequency",
    "DayOfWeek",
    "ScheduleExecutionMode",
    "MisfirePolicy",
    # Notification
    "Notification",
    "NotificationCategory",
]
