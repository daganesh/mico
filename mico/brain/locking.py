"""Single-writer file lock and per-track logical lock (PRD §3.3, AD-01).

Two independent primitives:

- ``FileLock`` / ``acquire_file_lock``: a cross-process exclusive lock on
  ``$MICO_HOME/.lock``, backed by ``fcntl.flock`` on POSIX and
  ``msvcrt.locking`` on Windows (stdlib only, per AD-14). This is the
  "single-writer" mechanism from PRD §3.3: every mutating operation holds
  it for the duration of the mutation.
- ``TrackLockManager``: an in-process ``asyncio.Lock`` keyed by track slug,
  used to serialize concurrent Runs against the same Track within one
  process. It is intentionally *not* cross-process -- PRD §3.3 only
  requires the file lock to span processes; the per-track rule ("a second
  interactive Run is rejected, a scheduled Run is skipped") is enforced by
  the caller inspecting/acquiring this lock, not by this module.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 30.0
_POLL_INTERVAL_SECONDS = 0.05


class FileLockTimeout(RuntimeError):
    """Raised when a `FileLock` cannot be acquired within its timeout."""

    def __init__(
        self,
        path: Path,
        timeout_seconds: float,
        holder_pid: int | None,
        holder_operation: str | None,
    ) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.holder_pid = holder_pid
        self.holder_operation = holder_operation

        message = f"Timed out after {timeout_seconds}s waiting for exclusive lock on {path}"
        if holder_pid is not None:
            message += f" (held by PID {holder_pid}"
            if holder_operation:
                message += f", operation={holder_operation!r}"
            message += ")"
        else:
            message += " (holder PID unknown)"
        super().__init__(message)


def _lock_fd_nonblocking(fd: int) -> bool:
    """Try to take an exclusive, non-blocking lock on `fd`. Returns success."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def _unlock_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_holder_info(path: Path) -> tuple[int | None, str | None]:
    """Best-effort read of the PID/operation the current holder wrote in.

    This only works because `FileLock` itself writes "<pid> <operation>"
    into the lock file right after acquiring it -- `flock`/`msvcrt` locks
    carry no such metadata on their own.
    """
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    if not content:
        return None, None
    pid_str, _, operation = content.partition(" ")
    try:
        pid = int(pid_str)
    except ValueError:
        return None, None
    return pid, operation or None


class FileLock:
    """Cross-process exclusive lock on a single file path.

    Usable as an async context manager:

        async with FileLock(mico_home / ".lock", operation="refresh"):
            ...

    `fcntl.flock`/`msvcrt.locking` are blocking syscalls, so the actual
    acquire/release happen in a worker thread via `asyncio.to_thread` --
    otherwise a contended lock would stall the whole event loop for up to
    `timeout_seconds`, not just the caller waiting on it.
    """

    def __init__(
        self,
        path: Path,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        operation: str | None = None,
    ) -> None:
        self._path = path
        self._timeout_seconds = timeout_seconds
        self._operation = operation
        self._fd: int | None = None

    def _acquire_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            deadline = time.monotonic() + self._timeout_seconds
            while not _lock_fd_nonblocking(fd):
                if time.monotonic() >= deadline:
                    holder_pid, holder_operation = _read_holder_info(self._path)
                    raise FileLockTimeout(
                        self._path, self._timeout_seconds, holder_pid, holder_operation
                    )
                time.sleep(_POLL_INTERVAL_SECONDS)

            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            payload = f"{os.getpid()} {self._operation or ''}".rstrip() + "\n"
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        self._fd = fd

    def _release_sync(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            _unlock_fd(fd)
        finally:
            os.close(fd)

    async def __aenter__(self) -> FileLock:
        await asyncio.to_thread(self._acquire_sync)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await asyncio.to_thread(self._release_sync)


def acquire_file_lock(
    path: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    operation: str | None = None,
) -> FileLock:
    """Return a `FileLock` for `path`, ready to use as `async with ...:`."""
    return FileLock(path, timeout_seconds=timeout_seconds, operation=operation)


class TrackLockManager:
    """In-process async lock keyed by track slug (PRD §3.3).

    Prevents concurrent Runs against the same Track within one process.
    Locks are created lazily per slug and kept for the process lifetime;
    this is deliberately not cross-process -- the cross-process guarantee
    is `FileLock` above.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, slug: str) -> asyncio.Lock:
        lock = self._locks.get(slug)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[slug] = lock
        return lock

    def locked(self, slug: str) -> bool:
        """Whether `slug` is currently held, without acquiring it."""
        lock = self._locks.get(slug)
        return lock is not None and lock.locked()

    @asynccontextmanager
    async def lock(self, slug: str) -> AsyncIterator[None]:
        async with self._get_lock(slug):
            yield
