"""Structured JSON logging (AD-13).

Two sinks are wired by :func:`configure_logging`: a console sink at a
caller-chosen level, and an optional per-run file sink that always receives
every record regardless of the console level ("the Run log must not
disappear because the console was set to warning" -- AD-13). Both sinks
share one :class:`JsonFormatter`, so every line on every sink is a single
JSON object with typed fields, and one redaction pass runs before a record
is serialized, never left to caller discipline at the log-call site.

``run_id`` correlation is automatic: :class:`RunIdFilter` reads a
``contextvars.ContextVar`` and stamps it onto every record, including
records emitted from tasks spawned with ``asyncio.create_task`` under a Run
(contextvars propagate into new tasks by default), so callers never have to
thread ``run_id`` through call signatures by hand.

Callers that need to attach extra structured fields (``track_slug``,
``operation``, ``error_class``, ``error_code``, ...) use :func:`log_extra`,
e.g. ``logger.info("...", extra=log_extra(operation="refresh"))``.

Security note (AD-13's "security tension with PRD Sec 12.3"): this module
has no notion of prompts or agent output yet -- that lands with the agent
integration tasks (M2.x). When those callers exist, full prompt/agent-output
detail must only ever be attached via ``log_extra`` at ``DEBUG``, never at a
default-enabled level, because it carries the entire brief and all evidence.
This module's job is only to make sure that whatever detail *is* passed
through ``log_extra`` still gets redacted and still lands in the file sink
even when the console is quieter.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

# Default correlation-id contextvar. Callers running work under a Run should
# `RUN_ID.set(run_id)` (or `.reset()` a token) around that work; a fresh
# ContextVar may also be passed to `configure_logging` instead, e.g. in tests.
RUN_ID: ContextVar[str | None] = ContextVar("mico_run_id", default=None)

REDACTED = "[REDACTED]"

# Key names that are sensitive regardless of what their value looks like.
_SENSITIVE_KEY_RE = re.compile(
    r"(api[-_]?key|access[-_]?key|secret|password|passwd|token|authorization|bearer)",
    re.IGNORECASE,
)

# Value shapes that look like a credential regardless of which field they're in.
_TOKEN_VALUE_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]


def _redact_string(value: str) -> str:
    result = value
    for pattern in _TOKEN_VALUE_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def redact_value(value: Any, key: str | None = None) -> Any:
    """Recursively strip key-shaped/value-shaped secrets from `value`.

    Applied to every record before it is serialized, per AD-13: the scrubber
    lives in the pipeline, not at call sites.
    """
    if key is not None and _SENSITIVE_KEY_RE.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact_value(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def log_extra(**fields: Any) -> dict[str, Any]:
    """Build the `extra=` kwarg for attaching structured detail to a log call.

    ``logger.info("refresh started", extra=log_extra(operation="refresh",
    track_slug="acme"))``. Fields passed here are redacted and merged into
    the JSON payload by :class:`JsonFormatter`. Detail containing full
    prompt/agent-output text must only be attached this way at DEBUG level.
    """
    return {"mico_detail": fields}


class RunIdFilter(logging.Filter):
    """Stamps `record.run_id` from a contextvar onto every record it sees."""

    def __init__(self, run_id_var: ContextVar[str | None]) -> None:
        super().__init__()
        self._run_id_var = run_id_var

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self._run_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Emits one JSON object per line with typed fields, redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        run_id = getattr(record, "run_id", None)
        if run_id is not None:
            payload["run_id"] = run_id
        detail = getattr(record, "mico_detail", None)
        if detail:
            payload.update(detail)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact_value(payload), default=str, sort_keys=True)


def _level_from_name(name: str) -> int:
    level = logging.getLevelName(name.upper())
    if not isinstance(level, int):
        raise ValueError(f"Unknown log level: {name!r}")
    return level


def configure_logging(
    console_level: str,
    run_log_path: Path | None,
    run_id_var: ContextVar[str | None] = RUN_ID,
    *,
    logger: logging.Logger | None = None,
    console_stream: TextIO | None = None,
) -> logging.Logger:
    """Wire up the console + per-run-file JSON sinks on `logger`.

    `run_log_path` is caller-supplied rather than hardcoded to
    `$MICO_HOME/runs/<date>/<run_id>.jsonl` -- there is no config/CLI loader
    yet to resolve `$MICO_HOME` from (that lands in a later task). The file
    sink, when given a path, always receives every record regardless of
    `console_level` (AD-13: the Run log must not disappear because the
    console was set to a higher level).

    `logger` defaults to the `"mico"` logger. Existing handlers on it are
    replaced so repeated calls (e.g. across tests) don't accumulate sinks.
    """
    target = logger if logger is not None else logging.getLogger("mico")
    for handler in list(target.handlers):
        target.removeHandler(handler)
    target.setLevel(logging.DEBUG)
    target.propagate = False

    run_id_filter = RunIdFilter(run_id_var)
    formatter = JsonFormatter()

    stream = console_stream if console_stream is not None else sys.stderr
    console_handler = logging.StreamHandler(stream)
    console_handler.setLevel(_level_from_name(console_level))
    console_handler.setFormatter(formatter)
    console_handler.addFilter(run_id_filter)
    target.addHandler(console_handler)

    if run_log_path is not None:
        run_log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(run_log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(run_id_filter)
        target.addHandler(file_handler)
        try:
            run_log_path.chmod(0o600)
        except OSError:
            pass

    return target
