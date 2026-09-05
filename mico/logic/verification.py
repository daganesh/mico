"""Verification Provider ABC (PRD §5.2, §7.2).

The Verification Provider is the "Stage 2" grounding check: a single
stateless call with no tools, no memory, and no session — deliberately
simpler than the `AgentProvider` shape used for brief authoring (§5.2).
Because its input/output contract is fixed and it never uses tools, it
must be swappable to any HTTP LLM API or a local model (e.g. Ollama) at
effectively zero code change (§5.2, §7.2) — this module defines that
contract only; the HTTP-backed and local-model implementations are
separate follow-up tasks.

Per §7.2, a call sees only file content — the prior brief, the proposed
brief, and evidence excerpts already present in the proposal. It never
sees agent reasoning or transcript; that black-box property is structural
here, not merely enforced, since `VerificationRequest` has no field that
could carry a transcript.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


class RubricKind(StrEnum):
    """Which grounding rubric a Stage 2 call should apply (§7.2).

    `refresh` (and similarly-shaped operations) checks the proposed brief
    against the evidence for source consistency; `condense` checks for
    information loss and unwarranted new claims instead.
    """

    SOURCE_CONSISTENCY = "source_consistency"
    INFORMATION_LOSS = "information_loss"


@dataclass(frozen=True)
class VerificationRequest:
    """Inputs to a single Stage 2 grounding call (§7.2).

    Deliberately limited to file content: `mico` only ever has the prior
    and proposed brief plus the evidence excerpts the proposal cites, never
    the agent's reasoning or transcript.
    """

    prior_brief: str
    proposed_brief: str
    evidence_excerpts: list[str]
    rubric: RubricKind


@dataclass(frozen=True)
class VerificationResult:
    """Output of a single Stage 2 grounding call (§7.2): a 0.0-1.0 score
    plus structured, machine-readable reasons (never raw model reasoning).
    """

    score: float
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be within [0.0, 1.0], got {self.score!r}")


class VerificationProvider(ABC):
    """Stage 2 grounding provider (§5.2): one stateless call, no tools, no
    memory. Any HTTP-backed LLM API or local model can implement this
    identically — the ABC is the entire swap surface.
    """

    @abstractmethod
    async def score(self, request: VerificationRequest) -> VerificationResult:
        """Score `request.proposed_brief` against `request.rubric` and
        return a grounding score plus structured reasons.
        """
        ...
