"""Schedule (PRD §11.1, AD-15 -- structured fields, not cron strings)."""

from __future__ import annotations

from datetime import datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from mico.brain.models.common import MicoModel, uuid7
from mico.brain.models.enums import (
    DayOfWeek,
    MisfirePolicy,
    RunOperation,
    ScheduleExecutionMode,
    ScheduleFrequency,
)

__all__ = ["Schedule"]


class Schedule(MicoModel):
    id: UUID = Field(default_factory=uuid7)
    track_id: UUID | None = None
    operation: RunOperation
    frequency: ScheduleFrequency
    time_of_day: time | None = None
    days_of_week: list[DayOfWeek] | None = None
    interval_hours: int | None = None
    timezone: str
    execution_mode: ScheduleExecutionMode = ScheduleExecutionMode.EMBEDDED
    misfire_policy: MisfirePolicy = MisfirePolicy.COALESCE
    enabled: bool = True
    suspended_until: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _validate_frequency_fields(self) -> Schedule:
        """§11.1: which fields apply depends on `frequency` -- `time_of_day`
        for daily/weekly, `days_of_week` for weekly, `interval_hours` for
        interval.
        """
        if self.frequency in (ScheduleFrequency.DAILY, ScheduleFrequency.WEEKLY):
            if self.time_of_day is None:
                raise ValueError("time_of_day is required when frequency is 'daily' or 'weekly'")
        if self.frequency is ScheduleFrequency.WEEKLY and not self.days_of_week:
            raise ValueError("days_of_week is required when frequency is 'weekly'")
        if self.frequency is ScheduleFrequency.INTERVAL and self.interval_hours is None:
            raise ValueError("interval_hours is required when frequency is 'interval'")
        return self
