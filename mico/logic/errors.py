"""Error classification scheme (AD-09).

Failures are classified by *what makes them go away*, not by where they
occurred. The resulting class drives a uniform affordance set so no UI
surface (CLI, web, notification panel, Ledger) special-cases individual
error types -- they all render the same `ErrorShape`.

This module is the **data model and pure classification functions only**.
The retry loop / circuit breaker that actually *executes* retries against
these classifications is a separate, later task (M2.10) -- nothing here
schedules a retry, sleeps, or touches a Run.

Two classifier adapters are provided, per AD-09's "Two classifier
adapters" section:

- `classify_verification_http_error` -- the Verification provider talks
  direct HTTP, so `mico` sees raw status codes and classification is
  exact.
- `classify_claude_code_error` -- Claude Code (the mandatory agent
  dependency) surfaces only agent output and/or a nonzero exit code, so
  classification is inherently lossier and, per AD-09, deliberately
  defaults ambiguous cases to Transient rather than risk stranding a
  retryable Run (see that function's docstring).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Error shape (AD-09 "Error shape")
# --------------------------------------------------------------------------


class ErrorClass(StrEnum):
    """The six recovery classes (AD-09), keyed by what resolves them."""

    TRANSIENT = "transient"
    DEPLETED = "depleted"
    BUDGET = "budget"
    CONFIG = "config"
    CONTENT = "content"
    FATAL = "fatal"


class Affordance(StrEnum):
    """User/automatic affordances a class may offer (AD-09)."""

    RETRY = "retry"
    EXTEND = "extend"
    ABANDON = "abandon"
    FORCE_APPLY = "force_apply"
    EDIT = "edit"
    FIX_CONFIG = "fix_config"
    WAIT = "wait"


class ErrorShape(BaseModel):
    """The one structure rendered by CLI, web UI, notifications, and Ledger.

    Per AD-13, `error_class`/`code` are structured log fields, so this
    model must serialize and round-trip cleanly through JSON.
    """

    error_class: ErrorClass
    #: Stable machine identifier (e.g. "AGENT_TIMEOUT", "STAGE1_STRUCTURE").
    #: Load-bearing per AD-09: the notification panel groups on it and the
    #: Ledger deduplicates on it.
    code: str
    #: Human-readable, one line.
    message: str
    #: Structured, class-specific payload (e.g. status_code, retry_after).
    detail: dict[str, Any] = Field(default_factory=dict)
    affordances: list[Affordance] = Field(default_factory=list)
    retry_count: int = 0
    retry_of: str | None = None


# --------------------------------------------------------------------------
# Retry bounds (AD-09 "Retry bounds")
# --------------------------------------------------------------------------
#
# AD-09 names three limits, "to prevent a local tool quietly burning
# budget overnight". Only the first has an exact number in AD-09; the
# other two are named here as the constants M2.10 (the retry loop /
# circuit breaker) will give real values and actually enforce -- this
# module only classifies errors, it never runs a loop.

#: 1. Per-Run cap on Transient retries (AD-09: "3, exponential backoff,
#: jittered"). The backoff/jitter behavior itself is M2.10's job; this is
#: just the bound.
TRANSIENT_RETRY_CAP_PER_RUN = 3

#: Deliberately lower than TRANSIENT_RETRY_CAP_PER_RUN. Used by
#: `classify_claude_code_error`'s ambiguous-exit default: AD-09 says an
#: agent-adapter ambiguous classification should default to Transient
#: "with a low retry cap", because "retrying twice on something
#: unretryable is cheap, while failing to retry something transient
#: strands a Run" -- a confirmed HTTP 5xx/429 is a stronger transient
#: signal than an unclassifiable nonzero exit, so it gets fewer retries.
AMBIGUOUS_AGENT_EXIT_RETRY_CAP = 1

#: 2. Total wall-clock ceiling across all retries of a Run, in seconds
#: (AD-09: "retries do not reset the budget clock"). AD-09 does not
#: commit to an exact value -- left `None` here as an explicit "not yet
#: specified" placeholder for M2.10 to fill in and enforce against a
#: Run's elapsed time. Naming it here (rather than a bare comment) gives
#: M2.10 one place to set it, per the "no magic numbers" standard.
WALL_CLOCK_RETRY_CEILING_SECONDS: int | None = None

#: 3. Per-provider circuit breaker: after N consecutive Transient
#: failures against one provider, stop retrying anything for a cooldown
#: and reclassify as Config (AD-09). AD-09 does not commit to an exact N
#: -- same placeholder treatment as above; M2.10 owns the real value and
#: the breaker implementation itself.
CIRCUIT_BREAKER_CONSECUTIVE_FAILURE_THRESHOLD: int | None = None


# --------------------------------------------------------------------------
# Verification-provider (direct HTTP) classifier adapter
# --------------------------------------------------------------------------

#: Substrings (checked case-insensitively) that mark a response body as
#: signaling quota/credit exhaustion rather than an ordinary rate limit.
#: ASSUMPTION (documented per the task, since AD-09 leaves detection
#: mechanics to us): there is no universal status code for "out of
#: quota" -- providers commonly reuse 429 for both ordinary rate limiting
#: and hard quota exhaustion, distinguished only by body content, or use
#: 402 Payment Required for the latter. We therefore treat a bare 402 as
#: always Depleted, and treat 429 as Depleted only when the body matches
#: one of these markers, else as an ordinary rate limit (Transient).
DEPLETED_BODY_MARKERS: tuple[str, ...] = (
    "insufficient_quota",
    "quota_exceeded",
    "quota",
    "hard cap",
    "credit balance",
    "out of credits",
    "billing",
)


def classify_verification_http_error(
    status_code: int | None,
    *,
    retry_after: str | None = None,
    body: str | None = None,
    transport_reason: str | None = None,
    retry_count: int = 0,
    retry_of: str | None = None,
) -> ErrorShape:
    """Classify a Verification-provider (direct HTTP) failure (AD-09).

    `status_code` is `None` for failures that never produced an HTTP
    response at all -- network blip, connection reset, read timeout --
    in which case `transport_reason` should briefly describe what
    happened. Every other branch maps a raw status code (and, for 429,
    the `retry-after` header) to a class; per AD-09 "classification is
    exact" for this adapter, since `mico` sees the real status.

    `retry-after` is carried through in `detail` rather than consumed
    here -- AD-09 says to "honour retry-after rather than an own backoff
    curve", which is the future retry loop's (M2.10) job, not this
    classifier's.
    """
    if status_code is None:
        return ErrorShape(
            error_class=ErrorClass.TRANSIENT,
            code="VERIFICATION_TRANSPORT_ERROR",
            message=(
                "Verification provider request failed before a response: "
                f"{transport_reason or 'unknown transport error'}."
            ),
            detail={"transport_reason": transport_reason},
            affordances=[Affordance.RETRY],
            retry_count=retry_count,
            retry_of=retry_of,
        )

    body_lower = (body or "").lower()
    is_depleted = status_code == 402 or any(
        marker in body_lower for marker in DEPLETED_BODY_MARKERS
    )

    if is_depleted:
        return ErrorShape(
            error_class=ErrorClass.DEPLETED,
            code="VERIFICATION_DEPLETED",
            message="Verification provider reports quota/credits exhausted or a hard cap reached.",
            detail={"status_code": status_code, "body_snippet": (body or "")[:500]},
            affordances=[Affordance.WAIT],
            retry_count=retry_count,
            retry_of=retry_of,
        )

    if status_code == 429:
        return ErrorShape(
            error_class=ErrorClass.TRANSIENT,
            code="VERIFICATION_RATE_LIMITED",
            message="Verification provider rate-limited the request (429).",
            detail={"status_code": status_code, "retry_after": retry_after},
            affordances=[Affordance.RETRY],
            retry_count=retry_count,
            retry_of=retry_of,
        )

    if 500 <= status_code < 600:
        return ErrorShape(
            error_class=ErrorClass.TRANSIENT,
            code="VERIFICATION_SERVER_ERROR",
            message=f"Verification provider returned a server error ({status_code}).",
            detail={"status_code": status_code, "retry_after": retry_after},
            affordances=[Affordance.RETRY],
            retry_count=retry_count,
            retry_of=retry_of,
        )

    if status_code == 401:
        return ErrorShape(
            error_class=ErrorClass.CONFIG,
            code="VERIFICATION_INVALID_API_KEY",
            message="Verification provider rejected the API key (401).",
            detail={"status_code": status_code},
            affordances=[Affordance.FIX_CONFIG],
            retry_count=retry_count,
            retry_of=retry_of,
        )

    if status_code == 403:
        return ErrorShape(
            error_class=ErrorClass.CONFIG,
            code="VERIFICATION_INSUFFICIENT_PERMISSIONS",
            message=(
                "Verification provider denied the request: insufficient permissions "
                "or model not enabled (403)."
            ),
            detail={"status_code": status_code},
            affordances=[Affordance.FIX_CONFIG],
            retry_count=retry_count,
            retry_of=retry_of,
        )

    # No AD-09 table entry covers this status. Defaulting to Fatal (rather
    # than silently guessing Transient/Config) surfaces it to the Ledger
    # for a human to extend the table with a new named case.
    return ErrorShape(
        error_class=ErrorClass.FATAL,
        code="VERIFICATION_UNCLASSIFIED_STATUS",
        message=f"Verification provider returned an unclassified status ({status_code}).",
        detail={"status_code": status_code, "body_snippet": (body or "")[:500]},
        affordances=[],
        retry_count=retry_count,
        retry_of=retry_of,
    )


# --------------------------------------------------------------------------
# Claude Code (agent) classifier adapter
# --------------------------------------------------------------------------

#: Substrings (checked case-insensitively against combined stderr/stdout)
#: recognized as "Claude Code isn't on PATH / isn't installed".
NOT_INSTALLED_MARKERS: tuple[str, ...] = (
    "command not found",
    "claude: not found",
    "no such file or directory",
    "is not recognized as an internal or external command",
)

#: Substrings recognized as "Claude Code is installed but not
#: authenticated" (or the API key it's using is rejected).
NOT_AUTHENTICATED_MARKERS: tuple[str, ...] = (
    "not authenticated",
    "not logged in",
    "please run `claude login`",
    "please run claude login",
    "invalid api key",
    "unauthorized",
)


def classify_claude_code_error(
    exit_code: int,
    *,
    stderr: str | None = None,
    stdout_tail: str | None = None,
    retry_count: int = 0,
    retry_of: str | None = None,
) -> ErrorShape:
    """Classify a Claude Code (agent subprocess) failure (AD-09).

    Call this only for a failed invocation (nonzero exit, or a zero exit
    that produced no usable proposal upstream) -- it does not itself
    check `exit_code == 0`.

    This adapter is inherently lossier than the HTTP one: `mico` sees a
    message and/or an exit code, not a status code, and Claude Code may
    already have retried internally (AD-09). Only two signals are
    confidently recognized here (not installed, not authenticated);
    everything else is genuinely ambiguous.

    **Deliberate, non-obvious default** (AD-09, "Two classifier
    adapters"): an ambiguous nonzero exit defaults to **Transient with a
    low retry cap** (`AMBIGUOUS_AGENT_EXIT_RETRY_CAP`), *not* Config or
    Fatal. This is AD-09's explicit rule, quoted here because it is easy
    to get backwards: "where classification is ambiguous it defaults to
    Transient with a low retry cap -- retrying twice on something
    unretryable is cheap, while failing to retry something transient
    strands a Run." So an unrecognized agent failure is optimistically
    treated as retryable, capped low specifically because that optimism
    is often wrong.
    """
    combined = f"{stderr or ''}\n{stdout_tail or ''}".lower()

    if any(marker in combined for marker in NOT_INSTALLED_MARKERS):
        return ErrorShape(
            error_class=ErrorClass.CONFIG,
            code="CLAUDE_CODE_NOT_INSTALLED",
            message="Claude Code CLI does not appear to be installed or is not on PATH.",
            detail={"exit_code": exit_code, "stderr_snippet": (stderr or "")[:500]},
            affordances=[Affordance.FIX_CONFIG],
            retry_count=retry_count,
            retry_of=retry_of,
        )

    if any(marker in combined for marker in NOT_AUTHENTICATED_MARKERS):
        return ErrorShape(
            error_class=ErrorClass.CONFIG,
            code="CLAUDE_CODE_NOT_AUTHENTICATED",
            message="Claude Code CLI is not authenticated.",
            detail={"exit_code": exit_code, "stderr_snippet": (stderr or "")[:500]},
            affordances=[Affordance.FIX_CONFIG],
            retry_count=retry_count,
            retry_of=retry_of,
        )

    return ErrorShape(
        error_class=ErrorClass.TRANSIENT,
        code="CLAUDE_CODE_AMBIGUOUS_EXIT",
        message=(
            f"Claude Code exited with an unrecognized nonzero status ({exit_code}); "
            "defaulting to a retryable transient failure per AD-09."
        ),
        detail={
            "exit_code": exit_code,
            "stderr_snippet": (stderr or "")[:500],
            "retry_cap": AMBIGUOUS_AGENT_EXIT_RETRY_CAP,
        },
        affordances=[Affordance.RETRY],
        retry_count=retry_count,
        retry_of=retry_of,
    )
