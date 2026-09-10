"""Tests for mico/logic/errors.py (AD-09 error classification)."""

from __future__ import annotations

import pytest

from mico.logic.errors import (
    AMBIGUOUS_AGENT_EXIT_RETRY_CAP,
    TRANSIENT_RETRY_CAP_PER_RUN,
    Affordance,
    ErrorClass,
    ErrorShape,
    classify_claude_code_error,
    classify_verification_http_error,
)

# --------------------------------------------------------------------------
# HTTP adapter -- AD-09 "Classification of named failures" table
# --------------------------------------------------------------------------


def test_network_blip_is_transient() -> None:
    shape = classify_verification_http_error(None, transport_reason="connection_reset")

    assert shape.error_class is ErrorClass.TRANSIENT
    assert shape.affordances == [Affordance.RETRY]
    assert shape.detail["transport_reason"] == "connection_reset"


def test_read_timeout_is_transient() -> None:
    shape = classify_verification_http_error(None, transport_reason="read_timeout")

    assert shape.error_class is ErrorClass.TRANSIENT


@pytest.mark.parametrize("status_code", [500, 502, 503, 599])
def test_5xx_is_transient(status_code: int) -> None:
    shape = classify_verification_http_error(status_code)

    assert shape.error_class is ErrorClass.TRANSIENT
    assert shape.code == "VERIFICATION_SERVER_ERROR"
    assert shape.detail["status_code"] == status_code


def test_429_without_depletion_signal_is_transient_and_carries_retry_after() -> None:
    shape = classify_verification_http_error(429, retry_after="30", body="rate limit exceeded")

    assert shape.error_class is ErrorClass.TRANSIENT
    assert shape.code == "VERIFICATION_RATE_LIMITED"
    assert shape.detail["retry_after"] == "30"
    assert shape.affordances == [Affordance.RETRY]


@pytest.mark.parametrize(
    "body",
    [
        '{"error": {"type": "insufficient_quota"}}',
        "You have exceeded your current quota, please check your plan.",
        "Billing hard limit reached for this account.",
    ],
)
def test_429_with_quota_signal_is_depleted(body: str) -> None:
    shape = classify_verification_http_error(429, retry_after="3600", body=body)

    assert shape.error_class is ErrorClass.DEPLETED
    assert shape.code == "VERIFICATION_DEPLETED"
    assert shape.affordances == [Affordance.WAIT]


def test_bare_402_is_depleted_regardless_of_body() -> None:
    shape = classify_verification_http_error(402, body="Payment Required")

    assert shape.error_class is ErrorClass.DEPLETED


def test_401_is_config() -> None:
    shape = classify_verification_http_error(401)

    assert shape.error_class is ErrorClass.CONFIG
    assert shape.code == "VERIFICATION_INVALID_API_KEY"
    assert shape.affordances == [Affordance.FIX_CONFIG]


def test_403_is_config() -> None:
    shape = classify_verification_http_error(403)

    assert shape.error_class is ErrorClass.CONFIG
    assert shape.code == "VERIFICATION_INSUFFICIENT_PERMISSIONS"
    assert shape.affordances == [Affordance.FIX_CONFIG]


def test_unclassified_status_defaults_to_fatal() -> None:
    shape = classify_verification_http_error(418, body="I'm a teapot")

    assert shape.error_class is ErrorClass.FATAL
    assert shape.code == "VERIFICATION_UNCLASSIFIED_STATUS"


def test_retry_count_and_retry_of_pass_through() -> None:
    shape = classify_verification_http_error(500, retry_count=2, retry_of="run_abc")

    assert shape.retry_count == 2
    assert shape.retry_of == "run_abc"


# --------------------------------------------------------------------------
# Claude Code adapter
# --------------------------------------------------------------------------


def test_claude_code_not_installed_is_config() -> None:
    shape = classify_claude_code_error(127, stderr="bash: claude: command not found")

    assert shape.error_class is ErrorClass.CONFIG
    assert shape.code == "CLAUDE_CODE_NOT_INSTALLED"
    assert shape.affordances == [Affordance.FIX_CONFIG]


def test_claude_code_not_authenticated_is_config() -> None:
    shape = classify_claude_code_error(
        1, stderr="Error: not authenticated. Please run `claude login`."
    )

    assert shape.error_class is ErrorClass.CONFIG
    assert shape.code == "CLAUDE_CODE_NOT_AUTHENTICATED"
    assert shape.affordances == [Affordance.FIX_CONFIG]


def test_claude_code_ambiguous_exit_defaults_to_transient_with_low_cap() -> None:
    """AD-09's explicit rule: ambiguous agent-adapter failures default to
    Transient with a low retry cap, distinct from (and lower than) the
    general per-Run transient cap, so a genuinely unretryable failure
    doesn't get retried as many times as a confirmed-transient HTTP one.
    """
    shape = classify_claude_code_error(1, stderr="panic: unexpected internal error")

    assert shape.error_class is ErrorClass.TRANSIENT
    assert shape.code == "CLAUDE_CODE_AMBIGUOUS_EXIT"
    assert shape.affordances == [Affordance.RETRY]
    assert shape.detail["retry_cap"] == AMBIGUOUS_AGENT_EXIT_RETRY_CAP
    assert AMBIGUOUS_AGENT_EXIT_RETRY_CAP < TRANSIENT_RETRY_CAP_PER_RUN


def test_claude_code_ambiguous_exit_with_no_output_at_all() -> None:
    shape = classify_claude_code_error(1)

    assert shape.error_class is ErrorClass.TRANSIENT
    assert shape.code == "CLAUDE_CODE_AMBIGUOUS_EXIT"


# --------------------------------------------------------------------------
# Error shape serialization round-trip (AD-13: error_class/code are
# structured log fields)
# --------------------------------------------------------------------------


def test_error_shape_round_trips_through_json() -> None:
    original = ErrorShape(
        error_class=ErrorClass.BUDGET,
        code="AGENT_TIMEOUT",
        message="Agent invocation exceeded its budget.",
        detail={"elapsed_seconds": 720, "budget_seconds": 600},
        affordances=[Affordance.EXTEND, Affordance.ABANDON],
        retry_count=1,
        retry_of="run_xyz",
    )

    restored = ErrorShape.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.error_class is ErrorClass.BUDGET
    assert restored.affordances == [Affordance.EXTEND, Affordance.ABANDON]


def test_error_shape_defaults() -> None:
    shape = ErrorShape(error_class=ErrorClass.FATAL, code="UNHANDLED_EXCEPTION", message="boom")

    assert shape.detail == {}
    assert shape.affordances == []
    assert shape.retry_count == 0
    assert shape.retry_of is None
