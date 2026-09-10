"""Evidence Pointer (PRD §2.4)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from mico.brain.models.common import MicoModel, utcnow, uuid7
from mico.brain.models.enums import EvidenceSourceType, ValidationStatus

__all__ = ["EvidencePointer"]


class EvidencePointer(MicoModel):
    id: UUID = Field(default_factory=uuid7)
    track_id: UUID
    uri: str
    label: str
    source_type: EvidenceSourceType
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_validated_at: datetime | None = None
    validation_status: ValidationStatus = ValidationStatus.UNCHECKED
    consecutive_failures: int = 0
