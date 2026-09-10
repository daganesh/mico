"""Track (PRD §2.1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from mico.brain.models.common import SLUG_PATTERN, MicoModel, utcnow, uuid7
from mico.brain.models.enums import AutomationMode, Priority, TrackStatus, TrackType

__all__ = ["Track"]

_ONGOING_DEFAULT_REFRESH_INTERVAL = timedelta(days=7)


class Track(MicoModel):
    id: UUID = Field(default_factory=uuid7)
    slug: Annotated[str, Field(pattern=SLUG_PATTERN)]
    title: Annotated[str, Field(max_length=120)]
    type: TrackType
    priority: Priority
    status: TrackStatus = TrackStatus.ACTIVE
    starred: bool = False
    category: str | None = None
    due_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_verified_at: datetime | None = None
    refresh_interval_hint: timedelta | None = None
    automation_mode: AutomationMode = AutomationMode.PROPOSAL

    @model_validator(mode="after")
    def _validate_due_at(self) -> Track:
        """PRD §2.1: `due_at` is "required iff `type = deliverable`"."""
        if self.type is TrackType.DELIVERABLE and self.due_at is None:
            raise ValueError("due_at is required when type is 'deliverable'")
        if self.type is TrackType.ONGOING and self.due_at is not None:
            raise ValueError("due_at must be null when type is 'ongoing'")
        return self

    @model_validator(mode="after")
    def _default_refresh_interval(self) -> Track:
        """PRD §2.1: "Default 7d for `ongoing`, null for `deliverable`"."""
        if self.refresh_interval_hint is None and self.type is TrackType.ONGOING:
            self.refresh_interval_hint = _ONGOING_DEFAULT_REFRESH_INTERVAL
        return self
