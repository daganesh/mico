"""Ledger Entry (PRD §2.6)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from mico.brain.models.common import MicoModel, utcnow
from mico.brain.models.enums import (
    ExportState,
    LedgerOrigin,
    LedgerSeverity,
    LedgerStatus,
    LedgerType,
)

__all__ = ["LedgerEntry"]


class LedgerEntry(MicoModel):
    """PRD §2.6: `id` is "Sequential, referenced as `#104`" -- assigned by
    the store on insert, unlike the UUIDv7 ids used elsewhere.
    """

    id: int
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    component: str
    severity: LedgerSeverity
    type: LedgerType
    origin: LedgerOrigin
    title: str
    description: str
    status: LedgerStatus = LedgerStatus.OPEN
    run_id: UUID | None = None
    export_state: ExportState = ExportState.LOCAL
    exported_url: str | None = None
