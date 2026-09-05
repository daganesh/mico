"""Tests for mico.logic.logging_setup (AD-13)."""

from __future__ import annotations

import asyncio
import contextvars
import io
import json
import logging
from pathlib import Path

import pytest

from mico.logic.logging_setup import (
    RUN_ID,
    configure_logging,
    log_extra,
    redact_value,
)


def _fresh_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    return logger


def test_json_lines_have_valid_structure_and_typed_fields() -> None:
    stream = io.StringIO()
    logger = _fresh_logger("mico.test.json_structure")
    configure_logging(
        console_level="INFO",
        run_log_path=None,
        run_id_var=RUN_ID,
        logger=logger,
        console_stream=stream,
    )

    logger.info("hello world", extra=log_extra(operation="refresh", track_slug="acme"))

    line = stream.getvalue().strip()
    payload = json.loads(line)
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "mico.test.json_structure"
    assert payload["operation"] == "refresh"
    assert payload["track_slug"] == "acme"
    assert "timestamp" in payload


def test_run_id_propagates_from_contextvar_and_is_absent_outside_a_run() -> None:
    stream = io.StringIO()
    logger = _fresh_logger("mico.test.run_id")
    run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "test_run_id", default=None
    )
    configure_logging(
        console_level="INFO",
        run_log_path=None,
        run_id_var=run_id_var,
        logger=logger,
        console_stream=stream,
    )

    token = run_id_var.set("run-123")
    try:
        logger.info("inside run")
    finally:
        run_id_var.reset(token)
    logger.info("outside run")

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[0]["run_id"] == "run-123"
    assert "run_id" not in lines[1]


async def test_run_id_propagates_into_asyncio_create_task() -> None:
    stream = io.StringIO()
    logger = _fresh_logger("mico.test.run_id_async")
    run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "test_run_id_async", default=None
    )
    configure_logging(
        console_level="INFO",
        run_log_path=None,
        run_id_var=run_id_var,
        logger=logger,
        console_stream=stream,
    )

    async def _log_from_task() -> None:
        logger.info("from task")

    token = run_id_var.set("run-async-1")
    try:
        task = asyncio.create_task(_log_from_task())
        await task
    finally:
        run_id_var.reset(token)

    payload = json.loads(stream.getvalue().strip())
    assert payload["run_id"] == "run-async-1"


def test_redact_value_strips_key_shaped_and_value_shaped_secrets() -> None:
    secret = "sk-ant-api03-" + "x" * 40
    result = redact_value({"api_key": "irrelevant-shape", "note": f"token was {secret}"})

    assert result["api_key"] == "[REDACTED]"
    assert secret not in result["note"]
    assert "[REDACTED]" in result["note"]


def test_redact_value_recurses_into_lists_and_tuples() -> None:
    secret = "sk-ant-api03-" + "z" * 40
    result = redact_value([f"has {secret}", "plain", ("nested", f"also {secret}")])

    assert secret not in json.dumps(result)


def test_exception_info_is_formatted_and_redacted_in_the_payload() -> None:
    stream = io.StringIO()
    logger = _fresh_logger("mico.test.exception")
    configure_logging(
        console_level="INFO",
        run_log_path=None,
        run_id_var=RUN_ID,
        logger=logger,
        console_stream=stream,
    )

    secret = "sk-ant-api03-" + "w" * 40
    try:
        raise ValueError(f"boom {secret}")
    except ValueError:
        logger.exception("failed")

    payload = json.loads(stream.getvalue().strip())
    assert "exception" in payload
    assert "ValueError" in payload["exception"]
    assert secret not in payload["exception"]


def test_redaction_applies_before_serialization_in_the_handler() -> None:
    stream = io.StringIO()
    logger = _fresh_logger("mico.test.redaction_pipeline")
    configure_logging(
        console_level="INFO",
        run_log_path=None,
        run_id_var=RUN_ID,
        logger=logger,
        console_stream=stream,
    )

    secret = "sk-ant-api03-" + "y" * 40
    logger.info("token issued", extra=log_extra(api_key=secret))

    raw_output = stream.getvalue()
    assert secret not in raw_output
    payload = json.loads(raw_output.strip())
    assert payload["api_key"] == "[REDACTED]"


def test_file_sink_receives_debug_records_even_when_console_is_warning(
    tmp_path: Path,
) -> None:
    stream = io.StringIO()
    logger = _fresh_logger("mico.test.file_sink")
    run_log_path = tmp_path / "runs" / "run-1.jsonl"

    configure_logging(
        console_level="WARNING",
        run_log_path=run_log_path,
        run_id_var=RUN_ID,
        logger=logger,
        console_stream=stream,
    )

    logger.debug("debug detail", extra=log_extra(track_slug="acme"))

    assert stream.getvalue() == ""

    file_lines = run_log_path.read_text(encoding="utf-8").splitlines()
    assert len(file_lines) == 1
    payload = json.loads(file_lines[0])
    assert payload["message"] == "debug detail"
    assert payload["level"] == "DEBUG"

    mode = run_log_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_configure_logging_replaces_handlers_on_repeat_calls(tmp_path: Path) -> None:
    stream = io.StringIO()
    logger = _fresh_logger("mico.test.repeat_calls")

    kwargs = dict(
        console_level="INFO",
        run_log_path=None,
        run_id_var=RUN_ID,
        logger=logger,
        console_stream=stream,
    )
    configure_logging(**kwargs)
    configure_logging(**kwargs)

    logger.info("only once")

    assert len(stream.getvalue().strip().splitlines()) == 1


def test_unknown_log_level_raises() -> None:
    logger = _fresh_logger("mico.test.bad_level")
    with pytest.raises(ValueError, match="Unknown log level"):
        configure_logging(
            console_level="NOT_A_LEVEL", run_log_path=None, run_id_var=RUN_ID, logger=logger
        )
