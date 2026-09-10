"""Schedule value object + next-fire calculation (AD-15).

AD-15 rejects both APScheduler and croniter: minute-level granularity is
sufficient, and the only real schedule shapes this tool needs are "daily at
a time", "weekly on given days at a time", and "every N hours". Next-fire
calculation is therefore ordinary `datetime` arithmetic, with stdlib
`zoneinfo` doing the one genuinely hard part (DST transitions) that cron
libraries exist to solve.

`ScheduleSpec` here is the AD-15 "structured schedule value object" used
purely for fire-time calculation. It is distinct from the persisted
`mico.brain.models.Schedule` row (M1.3), which adds `id`/`track_id`/
`execution_mode`/`enabled` and other storage-level fields; reconciling the
two is a future integration task, not this one.

Out of scope here (AD-15 also calls for it, but it's task M3.7): the
`Scheduler` ABC (start/stop/register/wake loop).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, field_validator, model_validator

__all__ = [
    "Frequency",
    "Weekday",
    "ScheduleSpec",
    "NextFireCalculator",
    "ArithmeticNextFireCalculator",
]


class Frequency(StrEnum):
    """Supported schedule shapes (AD-15: the only ones this tool needs)."""

    DAILY = "daily"
    WEEKLY = "weekly"
    INTERVAL = "interval"


class Weekday(StrEnum):
    """ISO weekday abbreviations, ordered Monday-first to match `date.weekday()`."""

    MO = "MO"
    TU = "TU"
    WE = "WE"
    TH = "TH"
    FR = "FR"
    SA = "SA"
    SU = "SU"


# `date.weekday()` returns 0 for Monday .. 6 for Sunday; this list is
# index-aligned to that so `_WEEKDAY_ORDER[date.weekday()]` gives the Weekday.
_WEEKDAY_ORDER: list[Weekday] = [
    Weekday.MO,
    Weekday.TU,
    Weekday.WE,
    Weekday.TH,
    Weekday.FR,
    Weekday.SA,
    Weekday.SU,
]


class ScheduleSpec(BaseModel):
    """Structured schedule fields (AD-15) -- no cron strings.

    Only the fields relevant to `frequency` need to be set; the others are
    validated as required/forbidden accordingly:

    - ``daily``: requires `time_of_day`.
    - ``weekly``: requires `time_of_day` and a non-empty `days_of_week`.
    - ``interval``: requires a positive `interval_hours`.
    """

    frequency: Frequency
    time_of_day: time | None = None
    days_of_week: list[Weekday] | None = None
    interval_hours: int | None = None
    timezone: str

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value!r}") from exc
        return value

    @field_validator("time_of_day")
    @classmethod
    def _validate_time_of_day_naive(cls, value: time | None) -> time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("time_of_day must be naive; timezone is given separately")
        return value

    @model_validator(mode="after")
    def _validate_frequency_fields(self) -> ScheduleSpec:
        if self.frequency is Frequency.DAILY:
            if self.time_of_day is None:
                raise ValueError("daily schedules require time_of_day")
        elif self.frequency is Frequency.WEEKLY:
            if self.time_of_day is None:
                raise ValueError("weekly schedules require time_of_day")
            if not self.days_of_week:
                raise ValueError("weekly schedules require a non-empty days_of_week")
        elif self.frequency is Frequency.INTERVAL:
            if self.interval_hours is None:
                raise ValueError("interval schedules require interval_hours")
            if self.interval_hours <= 0:
                raise ValueError("interval_hours must be positive")
        return self

    def zone(self) -> ZoneInfo:
        """Resolve `timezone` to a `ZoneInfo` instance."""
        return ZoneInfo(self.timezone)


class NextFireCalculator(ABC):
    """Port for computing a schedule's next fire time (AD-15).

    The internal `ArithmeticNextFireCalculator` is the one implementation
    needed for v1; the ABC exists so a croniter- or APScheduler-backed
    implementation could be swapped in later without touching callers (the
    embedded `Scheduler` runner, M3.7).
    """

    @abstractmethod
    def next_fire_after(self, spec: ScheduleSpec, after: datetime) -> datetime | None:
        """Return the next time `spec` fires strictly after `after`.

        `after` must be timezone-aware. The returned datetime, when not
        `None`, is timezone-aware in `spec`'s timezone. `None` is reserved
        for schedule shapes with no future occurrence; none of the current
        three frequencies (daily/weekly/interval) ever produce it, since
        each is unboundedly periodic.
        """
        raise NotImplementedError  # pragma: no cover


def _resolve_local(naive: datetime, tz: ZoneInfo, *, prefer_earlier: bool = True) -> datetime:
    """Attach `tz` to a naive wall-clock datetime, handling DST gap/fold.

    - **Fold** (a fall-back wall-clock time that occurs twice): resolved via
      PEP 495's `fold` -- `prefer_earlier=True` (the default) picks the
      first occurrence, which is what "next fire after X" wants (fire as
      soon as the wall clock reaches that time).
    - **Gap** (a spring-forward wall-clock time that never occurs): detected
      by round-tripping through UTC and comparing wall clocks. Rather than
      silently returning a nonexistent local time, the candidate is shifted
      forward to the UTC instant its naive value would map to across the
      transition (i.e. the same "distance" past the gap that it would have
      been past the nominal time), landing after the clocks jump forward.
    """
    fold = 0 if prefer_earlier else 1
    candidate = naive.replace(tzinfo=tz, fold=fold)
    utc_equiv = candidate.astimezone(UTC)
    roundtrip = utc_equiv.astimezone(tz).replace(tzinfo=None)
    if roundtrip == naive:
        return candidate
    # Gap: `naive` falls inside a skipped interval. `utc_equiv` already
    # carries the correctly-shifted local wall clock for that UTC instant.
    return utc_equiv.astimezone(tz)


class ArithmeticNextFireCalculator(NextFireCalculator):
    """`zoneinfo`-based `NextFireCalculator` (AD-15): plain datetime arithmetic.

    Interval anchoring: interval boundaries are anchored to local midnight
    (00:00) on the day of `after`, in the schedule's timezone, then stepped
    forward by `interval_hours` in wall-clock time. This is a deliberate
    choice AD-15 leaves open -- it means "every 6 hours" fires at stable
    local wall-clock times (00:00, 06:00, 12:00, 18:00) rather than drifting
    by whatever offset shift a DST transition introduces.
    """

    def next_fire_after(self, spec: ScheduleSpec, after: datetime) -> datetime | None:
        if after.tzinfo is None:
            raise ValueError("`after` must be timezone-aware")

        tz = spec.zone()
        after_local = after.astimezone(tz)

        if spec.frequency is Frequency.DAILY:
            return self._next_daily(spec, after, after_local, tz)
        if spec.frequency is Frequency.WEEKLY:
            return self._next_weekly(spec, after, after_local, tz)
        if spec.frequency is Frequency.INTERVAL:
            return self._next_interval(spec, after, after_local, tz)
        raise AssertionError(f"unhandled frequency: {spec.frequency!r}")  # pragma: no cover

    def _next_daily(
        self, spec: ScheduleSpec, after: datetime, after_local: datetime, tz: ZoneInfo
    ) -> datetime:
        assert spec.time_of_day is not None
        candidate_date = after_local.date()
        for _ in range(2):
            naive = datetime.combine(candidate_date, spec.time_of_day)
            candidate = _resolve_local(naive, tz)
            if candidate > after:
                return candidate
            candidate_date += timedelta(days=1)
        raise AssertionError("daily next-fire search exceeded expected bound")  # pragma: no cover

    def _next_weekly(
        self, spec: ScheduleSpec, after: datetime, after_local: datetime, tz: ZoneInfo
    ) -> datetime:
        assert spec.time_of_day is not None
        assert spec.days_of_week
        allowed = set(spec.days_of_week)
        start_date = after_local.date()
        for offset in range(8):
            candidate_date = start_date + timedelta(days=offset)
            if _WEEKDAY_ORDER[candidate_date.weekday()] not in allowed:
                continue
            naive = datetime.combine(candidate_date, spec.time_of_day)
            candidate = _resolve_local(naive, tz)
            if candidate > after:
                return candidate
        raise AssertionError("weekly next-fire search exceeded expected bound")  # pragma: no cover

    def _next_interval(
        self, spec: ScheduleSpec, after: datetime, after_local: datetime, tz: ZoneInfo
    ) -> datetime:
        assert spec.interval_hours is not None
        step = timedelta(hours=spec.interval_hours)
        candidate_naive = datetime.combine(after_local.date(), time.min)
        candidate = _resolve_local(candidate_naive, tz)

        # Walk forward one interval at a time from local midnight. `after`
        # is always on the same day as this midnight, and a day is at most
        # ~25 wall-clock hours even across a DST transition, so this is
        # bounded to a small number of steps.
        while candidate <= after:
            candidate_naive += step
            candidate = _resolve_local(candidate_naive, tz)
        return candidate
