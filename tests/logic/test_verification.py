"""Tests for the VerificationProvider ABC (M3.1, PRD §5.2/§7.2)."""

from __future__ import annotations

import pytest

from mico.logic.verification import (
    RubricKind,
    VerificationProvider,
    VerificationRequest,
    VerificationResult,
)


class _FakeVerificationProvider(VerificationProvider):
    """Trivial in-test fake: no HTTP, no model, just a canned result."""

    def __init__(self, result: VerificationResult) -> None:
        self._result = result

    async def score(self, request: VerificationRequest) -> VerificationResult:
        return self._result


def test_abc_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        VerificationProvider()  # type: ignore[abstract]


def test_subclass_missing_score_cannot_be_instantiated() -> None:
    class _Incomplete(VerificationProvider):
        pass

    with pytest.raises(TypeError):
        _Incomplete()  # type: ignore[abstract]


async def test_fake_provider_satisfies_contract() -> None:
    expected = VerificationResult(score=0.92, reasons=["consistent with evidence"])
    provider: VerificationProvider = _FakeVerificationProvider(expected)

    request = VerificationRequest(
        prior_brief="# Track\n\nOld content.",
        proposed_brief="# Track\n\nNew content.",
        evidence_excerpts=["excerpt one", "excerpt two"],
        rubric=RubricKind.SOURCE_CONSISTENCY,
    )
    result = await provider.score(request)

    assert result is expected
    assert 0.0 <= result.score <= 1.0
    assert result.reasons == ["consistent with evidence"]


async def test_condense_rubric_is_distinct_from_refresh_rubric() -> None:
    provider: VerificationProvider = _FakeVerificationProvider(
        VerificationResult(score=0.5, reasons=[])
    )

    refresh_request = VerificationRequest(
        prior_brief="prior",
        proposed_brief="proposed",
        evidence_excerpts=[],
        rubric=RubricKind.SOURCE_CONSISTENCY,
    )
    condense_request = VerificationRequest(
        prior_brief="prior",
        proposed_brief="proposed",
        evidence_excerpts=[],
        rubric=RubricKind.INFORMATION_LOSS,
    )

    assert refresh_request.rubric != condense_request.rubric
    assert await provider.score(refresh_request) == await provider.score(condense_request)


def test_result_rejects_out_of_range_score() -> None:
    with pytest.raises(ValueError):
        VerificationResult(score=1.5, reasons=[])
    with pytest.raises(ValueError):
        VerificationResult(score=-0.1, reasons=[])


def test_result_defaults_reasons_to_empty_list() -> None:
    result = VerificationResult(score=0.75)
    assert result.reasons == []
