"""State Brief frontmatter and Brief Revision (PRD §2.2, §2.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from mico.brain.models.common import SLUG_PATTERN, MicoModel, utcnow, uuid7
from mico.brain.models.enums import ApprovedBy, RevisionSource, VerifierStage1Result

__all__ = ["BriefFrontmatter", "BriefRevision"]


class BriefFrontmatter(MicoModel):
    """The YAML frontmatter block of `brief.md` (PRD §2.2), not the whole file.

    The H2 section body (Ground Truth / Blockers / Open Threads / Recent
    Changes / Notes) is Markdown text, not modeled here -- it lives as
    `BriefRevision.content`.
    """

    track_slug: Annotated[str, Field(pattern=SLUG_PATTERN)]
    revision: Annotated[int, Field(ge=1)]
    generated_at: datetime = Field(default_factory=utcnow)
    generated_by: str
    run_id: UUID
    verifier_stage1: VerifierStage1Result
    verifier_stage2_score: float | None = None
    word_count: Annotated[int, Field(ge=0)]
    unattributed_statements: Annotated[int, Field(ge=0)] = 0
    change_summary: Annotated[str, Field(max_length=140)]
    # "`format_version` in frontmatter supports migration." (§2.2) -- may be
    # bumped as an int or carry a string tag; either is valid across format
    # revisions, so the type stays a union rather than picking one now.
    format_version: str | int = 1


class BriefRevision(MicoModel):
    """PRD §2.3: "Every accepted Mutation writes an immutable Revision."""

    id: UUID = Field(default_factory=uuid7)
    track_id: UUID
    revision: Annotated[int, Field(ge=1)]
    content: str
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    created_at: datetime = Field(default_factory=utcnow)
    source: RevisionSource
    run_id: UUID | None = None
    verifier_stage2_score: float | None = None
    approved_by: ApprovedBy
    change_summary: Annotated[str, Field(max_length=140)]
