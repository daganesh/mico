"""Run (PRD §2.5, AD-02, AD-07..AD-09, AD-11)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from mico.brain.models.common import MicoModel, uuid7
from mico.brain.models.enums import (
    AutomationMode,
    ErrorClass,
    RunOperation,
    RunOutcome,
    RunStatus,
    RunTrigger,
)

__all__ = ["Run"]


class Run(MicoModel):
    """AD-11: the row is written at start, not at end -- `status` (where the
    Run is now) and `outcome` (how it ended, `None` while in flight) are
    deliberately distinct fields, never conflated.
    """

    id: UUID = Field(default_factory=uuid7)
    track_id: UUID | None = None
    operation: RunOperation
    trigger: RunTrigger
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: RunStatus = RunStatus.RUNNING_AGENT
    outcome: RunOutcome | None = None
    agent_session_id: str | None = None
    attempt_count: int = 0
    stage1_failures: list[dict[str, Any]] | None = None
    stage2_score: float | None = None
    automation_mode: AutomationMode
    log_ref: str | None = None
    # AD-11/AD-09 consolidated fields:
    base_revision: int | None = None
    retry_of: UUID | None = None
    superseded_by: UUID | None = None
    run_config: dict[str, Any] = Field(default_factory=dict)
    error_class: ErrorClass | None = None
    error_code: str | None = None
