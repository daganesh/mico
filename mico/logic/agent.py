"""`AgentProvider` — the contract for invoking Claude Code as an agent turn.

Per AD-05, `mico` never owns a persistent agent process: every turn is a
fresh `claude -p [--resume <session_id>]` subprocess invocation, not a
long-lived connection. This module therefore models a **single invocation**
(:class:`AgentInvocation` in, :class:`AgentResult` out) rather than a
connection object with open/close lifecycle methods.

**Failure modeling.** Expected runtime outcomes — the agent process
completing, timing out, or failing to run at all (PRD §5.7: binary missing,
malformed `stream-json`, non-zero exit) — are all represented as data via
:class:`AgentResult.outcome`, never raised as exceptions. This keeps the
result usable directly by a persisted state machine (AD-11's Run) without
try/except control flow across a boundary that may be resumed after a
restart. Only programmer errors (e.g. an invalid :class:`AgentInvocation`)
are exceptions, and those are ordinary Python exceptions, not part of this
contract.

**Streaming.** The agent emits incremental `stream-json` output that a
caller (CLI/web chat rendering, AD-05's "per-Run stream buffer") may want
to observe live. This is modeled as an optional callback (`on_event`)
invoked once per :class:`AgentStreamEvent` as it arrives, plus the full
buffered sequence returned on :class:`AgentResult.events` for callers that
only need it after the fact (e.g. a reconnecting browser catching up, or a
test asserting on the full transcript).

No concrete implementation lives here — see the (future) subprocess-backed
provider and the fixture-writing mock provider, both of which implement
this ABC identically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentStreamEvent(BaseModel):
    """One incremental unit of `stream-json` output.

    The shape of `data` is owned by the concrete provider (real
    `stream-json` parsing is M2.2's job) — this layer only guarantees a
    discriminator (`kind`) and the raw payload survive intact.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    data: dict[str, Any]


class AgentOutcome(StrEnum):
    """How an invocation ended, scoped to this ABC (PRD §5.7).

    Distinct from `Run.outcome` (PRD §2.5), which also covers validation
    results (`stage1_rejected`, etc.) that this layer knows nothing about —
    callers (M2.5/M2.7) map `AgentOutcome` onto `Run.status`/`Run.outcome`.
    """

    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


StreamHandler = Callable[[AgentStreamEvent], Awaitable[None] | None]


class AgentInvocation(BaseModel):
    """One agent turn to run: `claude -p [--resume <session_id>]`."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    prompt: str
    cwd: Path
    session_id: str | None = None
    allowed_tools: list[str]
    timeout_seconds: int = Field(gt=0)


class AgentResult(BaseModel):
    """The outcome of one :class:`AgentInvocation`."""

    model_config = ConfigDict(frozen=True)

    outcome: AgentOutcome
    session_id: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_cost_usd: float | None = None
    events: tuple[AgentStreamEvent, ...] = ()

    @property
    def success(self) -> bool:
        return self.outcome is AgentOutcome.COMPLETED


class AgentProvider(ABC):
    """Runs one agent turn and reports what happened.

    Implementations (subprocess-backed, fixture-writing mock, …) must be
    interchangeable: callers depend only on this contract.
    """

    @abstractmethod
    async def invoke(
        self,
        invocation: AgentInvocation,
        on_event: StreamHandler | None = None,
    ) -> AgentResult:
        """Run `invocation` to completion and return its result.

        If `on_event` is given, it is called once per streamed event as it
        arrives, in order; the same events are also returned (buffered) on
        the result's `events` field.
        """
        raise NotImplementedError
