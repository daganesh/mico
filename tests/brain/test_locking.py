"""Tests for mico.brain.locking (PRD §3.3)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from mico.brain.locking import (
    FileLock,
    FileLockTimeout,
    TrackLockManager,
    _read_holder_info,
    acquire_file_lock,
)


async def test_file_lock_excludes_concurrent_acquire(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    held = FileLock(lock_path, operation="refresh")
    await held.__aenter__()
    try:
        contender = acquire_file_lock(lock_path, timeout_seconds=0.2, operation="condense")
        with pytest.raises(FileLockTimeout):
            async with contender:
                pass
    finally:
        await held.__aexit__(None, None, None)


async def test_file_lock_timeout_names_holder_pid_and_operation(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    held = FileLock(lock_path, operation="refresh")
    await held.__aenter__()
    try:
        contender = acquire_file_lock(lock_path, timeout_seconds=0.2)
        with pytest.raises(FileLockTimeout) as exc_info:
            async with contender:
                pass
    finally:
        await held.__aexit__(None, None, None)

    err = exc_info.value
    assert str(lock_path) in str(err)
    assert err.holder_pid == os.getpid()
    assert err.holder_operation == "refresh"
    assert "refresh" in str(err)


async def test_file_lock_is_released_and_reacquirable(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"

    async with acquire_file_lock(lock_path, operation="first"):
        pass

    # Should not raise/timeout now that the first holder has released.
    async with acquire_file_lock(lock_path, timeout_seconds=1.0, operation="second"):
        pass


async def test_file_lock_serializes_two_tasks(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    events: list[str] = []

    async def worker(name: str) -> None:
        async with acquire_file_lock(lock_path, timeout_seconds=5.0, operation=name):
            events.append(f"{name}-start")
            await asyncio.sleep(0.05)
            events.append(f"{name}-end")

    await asyncio.gather(worker("a"), worker("b"))

    # Whichever task ran first, it must fully finish before the other starts.
    assert events[0].endswith("-start")
    assert events[1].endswith("-end")
    assert events[0].split("-")[0] == events[1].split("-")[0]


async def test_track_lock_manager_serializes_same_slug() -> None:
    manager = TrackLockManager()
    events: list[str] = []

    async def worker(name: str) -> None:
        async with manager.lock("track-a"):
            events.append(f"{name}-start")
            await asyncio.sleep(0.05)
            events.append(f"{name}-end")

    await asyncio.gather(worker("a"), worker("b"))

    assert events[0].endswith("-start")
    assert events[1].endswith("-end")
    assert events[0].split("-")[0] == events[1].split("-")[0]


async def test_track_lock_manager_allows_different_slugs_concurrently() -> None:
    manager = TrackLockManager()
    events: list[str] = []

    async def worker(slug: str) -> None:
        async with manager.lock(slug):
            events.append(f"{slug}-start")
            await asyncio.sleep(0.05)
            events.append(f"{slug}-end")

    start = time.monotonic()
    await asyncio.gather(worker("track-a"), worker("track-b"))
    elapsed = time.monotonic() - start

    # Serialized would take ~0.1s; concurrent should take ~0.05s.
    assert elapsed < 0.1
    assert events[0].endswith("-start")
    assert events[1].endswith("-start")


def test_file_lock_timeout_message_when_holder_unknown(tmp_path: Path) -> None:
    err = FileLockTimeout(tmp_path / ".lock", 1.5, holder_pid=None, holder_operation=None)
    assert "holder PID unknown" in str(err)


async def test_release_without_acquire_is_a_noop(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / ".lock")
    await lock.__aexit__(None, None, None)


def test_read_holder_info_missing_file(tmp_path: Path) -> None:
    assert _read_holder_info(tmp_path / "nope.lock") == (None, None)


def test_read_holder_info_empty_file(tmp_path: Path) -> None:
    path = tmp_path / ".lock"
    path.write_text("", encoding="utf-8")
    assert _read_holder_info(path) == (None, None)


def test_read_holder_info_malformed_pid(tmp_path: Path) -> None:
    path = tmp_path / ".lock"
    path.write_text("not-a-pid refresh\n", encoding="utf-8")
    assert _read_holder_info(path) == (None, None)


def test_read_holder_info_pid_without_operation(tmp_path: Path) -> None:
    path = tmp_path / ".lock"
    path.write_text("4242\n", encoding="utf-8")
    assert _read_holder_info(path) == (4242, None)


async def test_track_lock_manager_locked_reports_state() -> None:
    manager = TrackLockManager()
    assert manager.locked("track-a") is False

    async with manager.lock("track-a"):
        assert manager.locked("track-a") is True

    assert manager.locked("track-a") is False
