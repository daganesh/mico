"""M2.1: `AgentProvider` ABC contract tests (interface only, no real agent)."""

from __future__ import annotations

from pathlib import Path

import pydantic
import pytest

from mico.logic.agent import (
    AgentInvocation,
    AgentOutcome,
    AgentProvider,
    AgentResult,
    AgentStreamEvent,
)


class _FakeAgentProvider(AgentProvider):
    """Trivial in-test fake — records what it was asked to do."""

    def __init__(self) -> None:
        self.invocations: list[AgentInvocation] = []

    async def invoke(self, invocation, on_event=None) -> AgentResult:  # type: ignore[no-untyped-def]
        self.invocations.append(invocation)
        event = AgentStreamEvent(kind="assistant", data={"text": "hi"})
        if on_event is not None:
            result = on_event(event)
            if result is not None:
                await result
        return AgentResult(
            outcome=AgentOutcome.COMPLETED,
            session_id="sess-123",
            exit_code=0,
            events=(event,),
        )


def _invocation(**overrides: object) -> AgentInvocation:
    defaults: dict[str, object] = {
        "prompt": "do the thing",
        "cwd": Path("/workspace/tracks/example"),
        "allowed_tools": ["Read", "Write"],
        "timeout_seconds": 600,
    }
    defaults.update(overrides)
    return AgentInvocation(**defaults)  # type: ignore[arg-type]


def test_fake_provider_satisfies_the_abc() -> None:
    provider = _FakeAgentProvider()
    assert isinstance(provider, AgentProvider)


def test_abc_rejects_incomplete_subclass() -> None:
    class _Incomplete(AgentProvider):
        pass

    with pytest.raises(TypeError):
        _Incomplete()  # type: ignore[abstract]


async def test_invoke_returns_result_and_records_invocation() -> None:
    provider = _FakeAgentProvider()
    invocation = _invocation()

    result = await provider.invoke(invocation)

    assert provider.invocations == [invocation]
    assert result.outcome is AgentOutcome.COMPLETED
    assert result.success is True
    assert result.session_id == "sess-123"
    assert result.events[0].kind == "assistant"


async def test_invoke_calls_on_event_callback_live() -> None:
    provider = _FakeAgentProvider()
    seen: list[AgentStreamEvent] = []

    async def on_event(event: AgentStreamEvent) -> None:
        seen.append(event)

    result = await provider.invoke(_invocation(), on_event=on_event)

    assert seen == list(result.events)


def test_invocation_is_frozen() -> None:
    invocation = _invocation()
    with pytest.raises(pydantic.ValidationError):
        invocation.prompt = "changed"  # type: ignore[misc]


def test_invocation_resume_session_id_optional() -> None:
    invocation = _invocation(session_id="prior-session")
    assert invocation.session_id == "prior-session"
    assert _invocation().session_id is None


def test_result_failed_outcome_is_not_success() -> None:
    result = AgentResult(outcome=AgentOutcome.TIMED_OUT, error_message="killed after 600s")
    assert result.success is False
    assert result.error_message == "killed after 600s"
