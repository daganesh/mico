"""Tests for mico/logic/scheduling.py (AD-15: ScheduleSpec + NextFireCalculator)."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from mico.logic.scheduling import (
    ArithmeticNextFireCalculator,
    Frequency,
    NextFireCalculator,
    ScheduleSpec,
    Weekday,
)

NY = ZoneInfo("America/New_York")


@pytest.fixture
def calc() -> ArithmeticNextFireCalculator:
    return ArithmeticNextFireCalculator()


# --- ScheduleSpec validation ---------------------------------------------


def test_daily_requires_time_of_day() -> None:
    with pytest.raises(ValidationError, match="time_of_day"):
        ScheduleSpec(frequency=Frequency.DAILY, timezone="UTC")


def test_weekly_requires_time_of_day_and_days() -> None:
    with pytest.raises(ValidationError, match="time_of_day"):
        ScheduleSpec(frequency=Frequency.WEEKLY, timezone="UTC", days_of_week=[Weekday.MO])
    with pytest.raises(ValidationError, match="days_of_week"):
        ScheduleSpec(frequency=Frequency.WEEKLY, timezone="UTC", time_of_day=time(9, 0))


def test_interval_requires_positive_interval_hours() -> None:
    with pytest.raises(ValidationError, match="interval_hours"):
        ScheduleSpec(frequency=Frequency.INTERVAL, timezone="UTC")
    with pytest.raises(ValidationError, match="positive"):
        ScheduleSpec(frequency=Frequency.INTERVAL, timezone="UTC", interval_hours=0)


def test_invalid_timezone_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ScheduleSpec(frequency=Frequency.DAILY, timezone="Not/AZone", time_of_day=time(9, 0))


def test_time_of_day_with_tzinfo_rejected() -> None:
    with pytest.raises(ValidationError, match="naive"):
        ScheduleSpec(
            frequency=Frequency.DAILY,
            timezone="UTC",
            time_of_day=time(9, 0, tzinfo=UTC),
        )


def test_valid_specs_construct_for_each_frequency() -> None:
    ScheduleSpec(frequency=Frequency.DAILY, timezone="UTC", time_of_day=time(9, 0))
    ScheduleSpec(
        frequency=Frequency.WEEKLY,
        timezone="UTC",
        time_of_day=time(9, 0),
        days_of_week=[Weekday.MO, Weekday.WE],
    )
    ScheduleSpec(frequency=Frequency.INTERVAL, timezone="UTC", interval_hours=6)


# --- NextFireCalculator ABC ------------------------------------------------


def test_next_fire_calculator_is_abstract() -> None:
    with pytest.raises(TypeError):
        NextFireCalculator()  # type: ignore[abstract]


def test_next_fire_after_requires_aware_datetime(calc: ArithmeticNextFireCalculator) -> None:
    spec = ScheduleSpec(frequency=Frequency.DAILY, timezone="UTC", time_of_day=time(9, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        calc.next_fire_after(spec, datetime(2026, 9, 5, 8, 0, 0))  # noqa: DTZ001


# --- daily -----------------------------------------------------------------


def test_daily_next_fire_later_today(calc: ArithmeticNextFireCalculator) -> None:
    spec = ScheduleSpec(frequency=Frequency.DAILY, timezone="UTC", time_of_day=time(9, 0))
    after = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)

    result = calc.next_fire_after(spec, after)

    assert result == datetime(2026, 9, 5, 9, 0, tzinfo=UTC)


def test_daily_next_fire_rolls_to_next_day_when_time_passed(
    calc: ArithmeticNextFireCalculator,
) -> None:
    spec = ScheduleSpec(frequency=Frequency.DAILY, timezone="UTC", time_of_day=time(9, 0))
    after = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)

    result = calc.next_fire_after(spec, after)

    assert result == datetime(2026, 9, 6, 9, 0, tzinfo=UTC)


# --- weekly ------------------------------------------------------------


def test_weekly_next_fire_same_week(calc: ArithmeticNextFireCalculator) -> None:
    spec = ScheduleSpec(
        frequency=Frequency.WEEKLY,
        timezone="UTC",
        time_of_day=time(10, 0),
        days_of_week=[Weekday.MO, Weekday.WE, Weekday.FR],
    )
    # 2026-09-07 is a Monday.
    after = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)

    result = calc.next_fire_after(spec, after)

    assert result == datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def test_weekly_next_fire_rolls_past_today_to_next_matching_weekday(
    calc: ArithmeticNextFireCalculator,
) -> None:
    spec = ScheduleSpec(
        frequency=Frequency.WEEKLY,
        timezone="UTC",
        time_of_day=time(10, 0),
        days_of_week=[Weekday.MO, Weekday.WE, Weekday.FR],
    )
    # 2026-09-07 is a Monday; 10:00 has already passed.
    after = datetime(2026, 9, 7, 11, 0, tzinfo=UTC)

    result = calc.next_fire_after(spec, after)

    # Next matching day is Wednesday 2026-09-09.
    assert result == datetime(2026, 9, 9, 10, 0, tzinfo=UTC)


def test_weekly_next_fire_wraps_to_next_week_when_only_day_already_passed(
    calc: ArithmeticNextFireCalculator,
) -> None:
    spec = ScheduleSpec(
        frequency=Frequency.WEEKLY,
        timezone="UTC",
        time_of_day=time(10, 0),
        days_of_week=[Weekday.MO],
    )
    after = datetime(2026, 9, 7, 11, 0, tzinfo=UTC)

    result = calc.next_fire_after(spec, after)

    assert result == datetime(2026, 9, 14, 10, 0, tzinfo=UTC)


# --- interval ----------------------------------------------------------


def test_interval_next_fire_boundary(calc: ArithmeticNextFireCalculator) -> None:
    spec = ScheduleSpec(frequency=Frequency.INTERVAL, timezone="UTC", interval_hours=6)
    after = datetime(2026, 9, 5, 7, 30, tzinfo=UTC)

    result = calc.next_fire_after(spec, after)

    assert result == datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def test_interval_next_fire_strictly_after_exact_boundary(
    calc: ArithmeticNextFireCalculator,
) -> None:
    spec = ScheduleSpec(frequency=Frequency.INTERVAL, timezone="UTC", interval_hours=6)
    after = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    result = calc.next_fire_after(spec, after)

    assert result == datetime(2026, 9, 5, 18, 0, tzinfo=UTC)


def test_interval_next_fire_crosses_midnight(calc: ArithmeticNextFireCalculator) -> None:
    spec = ScheduleSpec(frequency=Frequency.INTERVAL, timezone="UTC", interval_hours=6)
    after = datetime(2026, 9, 5, 23, 0, tzinfo=UTC)

    result = calc.next_fire_after(spec, after)

    assert result == datetime(2026, 9, 6, 0, 0, tzinfo=UTC)


# --- DST transitions -----------------------------------------------------


def test_daily_dst_spring_forward_gap_shifts_forward(
    calc: ArithmeticNextFireCalculator,
) -> None:
    """2023-03-12 America/New_York: 02:00-02:59 never occurs (clocks jump to 03:00)."""
    spec = ScheduleSpec(
        frequency=Frequency.DAILY, timezone="America/New_York", time_of_day=time(2, 30)
    )
    after = datetime(2023, 3, 12, 1, 0, tzinfo=NY)

    result = calc.next_fire_after(spec, after)

    assert result is not None
    assert result > after
    # The nonexistent 02:30 is shifted forward across the gap to 03:30 EDT.
    assert (result.hour, result.minute) == (3, 30)
    assert result.utcoffset().total_seconds() == -4 * 3600  # EDT
    assert result.astimezone(UTC) == datetime(2023, 3, 12, 7, 30, tzinfo=UTC)


def test_daily_dst_fall_back_fold_picks_earlier_occurrence(
    calc: ArithmeticNextFireCalculator,
) -> None:
    """2023-11-05 America/New_York: 01:00-01:59 occurs twice (EDT then EST)."""
    spec = ScheduleSpec(
        frequency=Frequency.DAILY, timezone="America/New_York", time_of_day=time(1, 30)
    )
    after = datetime(2023, 11, 5, 0, 0, tzinfo=NY)

    result = calc.next_fire_after(spec, after)

    assert result is not None
    assert (result.hour, result.minute) == (1, 30)
    # Earlier (DST/EDT, UTC-4) occurrence is chosen, not the later EST one.
    assert result.utcoffset().total_seconds() == -4 * 3600
    assert result.astimezone(UTC) == datetime(2023, 11, 5, 5, 30, tzinfo=UTC)


def test_interval_dst_spring_forward_does_not_duplicate_or_skip_incorrectly(
    calc: ArithmeticNextFireCalculator,
) -> None:
    spec = ScheduleSpec(
        frequency=Frequency.INTERVAL, timezone="America/New_York", interval_hours=1
    )
    after = datetime(2023, 3, 12, 1, 30, tzinfo=NY)

    result = calc.next_fire_after(spec, after)

    assert result is not None
    assert result > after
    # The 02:00 boundary is inside the gap; next real boundary is 03:00 EDT.
    assert (result.hour, result.minute) == (3, 0)
    assert result.astimezone(UTC) == datetime(2023, 3, 12, 7, 0, tzinfo=UTC)
