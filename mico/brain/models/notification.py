"""Notification (AD-10, AD-12)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from mico.brain.models.common import MicoModel, utcnow, uuid7
from mico.brain.models.enums import NotificationCategory

__all__ = ["Notification"]


class Notification(MicoModel):
    """AD-10: "Notifications reference their subject (`run_id`, `track_id`,
    `ledger_id`) rather than duplicating content." AD-12: `reason` combines
    with `run_id` as the reconciliation sweep's upsert key
    (`upsert notification keyed on (run_id, reason)`), and `dismissed_at` is
    meaningful only for `informational` entries -- actionable ones are
    resolved-or-not, derived from Run state, never dismissed.
    """

    id: UUID = Field(default_factory=uuid7)
    run_id: UUID | None = None
    track_id: UUID | None = None
    ledger_id: int | None = None
    category: NotificationCategory
    reason: str
    created_at: datetime = Field(default_factory=utcnow)
    dismissed_at: datetime | None = None

    @model_validator(mode="after")
    def _require_a_subject(self) -> Notification:
        if self.run_id is None and self.track_id is None and self.ledger_id is None:
            raise ValueError("at least one of run_id, track_id, or ledger_id must be set")
        return self

    @model_validator(mode="after")
    def _dismissed_at_only_for_informational(self) -> Notification:
        if self.category is NotificationCategory.ACTIONABLE and self.dismissed_at is not None:
            raise ValueError("dismissed_at is not meaningful for actionable notifications")
        return self
