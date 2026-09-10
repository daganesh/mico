"""Shared base model, timestamp helper, and slug pattern for `mico.brain.models`."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from mico.brain.models._uuid7 import uuid7

__all__ = ["MicoModel", "SLUG_PATTERN", "utcnow", "uuid7"]

# PRD §2.1: "[a-z0-9-]{3,48}, unique. CLI handle and directory name."
SLUG_PATTERN = r"^[a-z0-9-]{3,48}$"


def utcnow() -> datetime:
    return datetime.now(UTC)


class MicoModel(BaseModel):
    """Base for all `mico.brain` domain models.

    `extra="forbid"` catches typos/stale fields at construction time rather
    than silently dropping them; `validate_assignment=True` keeps invariants
    (e.g. Track.due_at) enforced across the object's lifetime, not just at
    construction.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
