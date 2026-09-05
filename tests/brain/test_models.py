"""Tests for mico.brain.models (task M1.3, PRD §2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mico.brain.models import (
    ApprovedBy,
    AutomationMode,
    BriefFrontmatter,
    BriefRevision,
    DayOfWeek,
    EvidencePointer,
    EvidenceSourceType,
    ExportState,
    LedgerEntry,
    LedgerOrigin,
    LedgerSeverity,
    LedgerStatus,
    LedgerType,
    MisfirePolicy,
    Notification,
    NotificationCategory,
    Priority,
    RevisionSource,
    Run,
    RunOperation,
    RunOutcome,
    RunStatus,
    RunTrigger,
    Schedule,
    ScheduleExecutionMode,
    ScheduleFrequency,
    Track,
    TrackStatus,
    TrackType,
    ValidationStatus,
    VerifierStage1Result,
    uuid7,
)

CONTENT_HASH = "a" * 64


# --- uuid7 -------------------------------------------------------------


def test_uuid7_has_correct_version_and_variant() -> None:
    generated = uuid7()
    assert generated.version == 7
    # RFC 9562 variant bits are "10xx" -> Python's `.variant` reports RFC_4122.
    assert str(generated.variant) == "specified in RFC 4122"


def test_uuid7_values_are_distinct() -> None:
    assert uuid7().int != uuid7().int


# --- Track ---------------------------------------------------------------


def test_track_valid_construction_deliverable() -> None:
    track = Track(
        slug="ship-v2",
        title="Ship v2",
        type=TrackType.DELIVERABLE,
        priority=Priority.P0,
        status=TrackStatus.ACTIVE,
        starred=True,
        due_at=datetime(2026, 12, 1, tzinfo=UTC),
    )
    assert track.type is TrackType.DELIVERABLE
    assert track.automation_mode is AutomationMode.PROPOSAL
    assert track.refresh_interval_hint is None
    assert isinstance(track.id, UUID)


def test_track_valid_construction_ongoing_defaults_refresh_interval() -> None:
    track = Track(
        slug="on-call-rotation",
        title="On-call rotation",
        type=TrackType.ONGOING,
        priority=Priority.P2,
    )
    assert track.due_at is None
    assert track.refresh_interval_hint == timedelta(days=7)


def test_track_ongoing_explicit_refresh_interval_is_respected() -> None:
    track = Track(
        slug="on-call-rotation",
        title="On-call rotation",
        type=TrackType.ONGOING,
        priority=Priority.P2,
        refresh_interval_hint=timedelta(days=3),
    )
    assert track.refresh_interval_hint == timedelta(days=3)


def test_track_deliverable_requires_due_at() -> None:
    with pytest.raises(ValidationError, match="due_at is required"):
        Track(
            slug="ship-v2",
            title="Ship v2",
            type=TrackType.DELIVERABLE,
            priority=Priority.P0,
        )


def test_track_ongoing_forbids_due_at() -> None:
    with pytest.raises(ValidationError, match="due_at must be null"):
        Track(
            slug="on-call-rotation",
            title="On-call rotation",
            type=TrackType.ONGOING,
            priority=Priority.P2,
            due_at=datetime(2026, 12, 1, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "slug",
    ["ab", "Has-Upper", "has_underscore", "has a space", "x" * 49, ""],
)
def test_track_slug_pattern_rejects_invalid_slugs(slug: str) -> None:
    with pytest.raises(ValidationError):
        Track(
            slug=slug,
            title="Title",
            type=TrackType.ONGOING,
            priority=Priority.P1,
        )


@pytest.mark.parametrize("slug", ["abc", "ship-v2", "a" * 48, "a-b-c-123"])
def test_track_slug_pattern_accepts_valid_slugs(slug: str) -> None:
    track = Track(slug=slug, title="Title", type=TrackType.ONGOING, priority=Priority.P1)
    assert track.slug == slug


def test_track_title_max_length_enforced() -> None:
    with pytest.raises(ValidationError):
        Track(
            slug="abc",
            title="x" * 121,
            type=TrackType.ONGOING,
            priority=Priority.P1,
        )


# --- BriefFrontmatter ------------------------------------------------------


def test_brief_frontmatter_valid_construction() -> None:
    fm = BriefFrontmatter(
        track_slug="architecture-migration",
        revision=47,
        generated_by="claude-code",
        run_id=uuid4(),
        verifier_stage1=VerifierStage1Result.PASS,
        verifier_stage2_score=0.91,
        word_count=312,
        unattributed_statements=2,
        change_summary="SecOps sign-off received; v2 endpoint unblocked",
    )
    assert fm.format_version == 1
    assert fm.verifier_stage1 is VerifierStage1Result.PASS


def test_brief_frontmatter_change_summary_max_length_enforced() -> None:
    with pytest.raises(ValidationError):
        BriefFrontmatter(
            track_slug="architecture-migration",
            revision=1,
            generated_by="claude-code",
            run_id=uuid4(),
            verifier_stage1=VerifierStage1Result.FAIL,
            word_count=0,
            change_summary="x" * 141,
        )


# --- BriefRevision -----------------------------------------------------


def test_brief_revision_valid_construction() -> None:
    revision = BriefRevision(
        track_id=uuid4(),
        revision=1,
        content="## Ground Truth\n",
        content_hash=CONTENT_HASH,
        source=RevisionSource.AGENT,
        run_id=uuid4(),
        approved_by=ApprovedBy.AUTONOMOUS,
        change_summary="Initial revision",
    )
    assert isinstance(revision.id, UUID)
    assert revision.source is RevisionSource.AGENT


def test_brief_revision_content_hash_pattern_enforced() -> None:
    with pytest.raises(ValidationError):
        BriefRevision(
            track_id=uuid4(),
            revision=1,
            content="body",
            content_hash="not-a-sha256-hex-digest",
            source=RevisionSource.USER_EDIT,
            approved_by=ApprovedBy.NA,
            change_summary="edit",
        )


# --- EvidencePointer -----------------------------------------------------


def test_evidence_pointer_valid_construction() -> None:
    pointer = EvidencePointer(
        track_id=uuid4(),
        uri="manual:standup-2026-09-01",
        label="Standup notes",
        source_type=EvidenceSourceType.MANUAL,
    )
    assert pointer.validation_status is ValidationStatus.UNCHECKED
    assert pointer.consecutive_failures == 0


# --- Run -------------------------------------------------------------------


def test_run_valid_construction_in_flight() -> None:
    run = Run(
        operation=RunOperation.REFRESH,
        trigger=RunTrigger.CLI,
        automation_mode=AutomationMode.PROPOSAL,
    )
    assert run.status is RunStatus.RUNNING_AGENT
    assert run.outcome is None
    assert run.run_config == {}


def test_run_valid_construction_terminal() -> None:
    run = Run(
        track_id=uuid4(),
        operation=RunOperation.REFRESH,
        trigger=RunTrigger.SCHEDULE,
        status=RunStatus.COMPLETE,
        outcome=RunOutcome.SUCCESS,
        automation_mode=AutomationMode.AUTONOMOUS,
        attempt_count=1,
    )
    assert run.status is RunStatus.COMPLETE
    assert run.outcome is RunOutcome.SUCCESS


def test_run_status_and_outcome_are_independent_fields() -> None:
    # AD-11: a conflict retry marks the loser `superseded` as a *status*,
    # while `outcome` records the specific reason -- the two must not be
    # collapsed into one enum.
    run = Run(
        operation=RunOperation.REFRESH,
        trigger=RunTrigger.CLI,
        status=RunStatus.SUPERSEDED,
        outcome=RunOutcome.CONFLICT,
        automation_mode=AutomationMode.PROPOSAL,
        superseded_by=uuid4(),
    )
    assert run.status is RunStatus.SUPERSEDED
    assert run.outcome is RunOutcome.CONFLICT
    assert run.superseded_by is not None


# --- LedgerEntry -----------------------------------------------------------


def test_ledger_entry_valid_construction() -> None:
    entry = LedgerEntry(
        id=104,
        component="logic.validator",
        severity=LedgerSeverity.HIGH,
        type=LedgerType.BUG,
        origin=LedgerOrigin.SYSTEM,
        title="3 consecutive rejections",
        description="Track x rejected 3 times in a row.",
    )
    assert entry.status is LedgerStatus.OPEN
    assert entry.export_state is ExportState.LOCAL


# --- Schedule ---------------------------------------------------------------


def test_schedule_valid_construction_weekly() -> None:
    schedule = Schedule(
        track_id=uuid4(),
        operation=RunOperation.REFRESH,
        frequency=ScheduleFrequency.WEEKLY,
        time_of_day=time(8, 0),
        days_of_week=[DayOfWeek.MO, DayOfWeek.WE, DayOfWeek.FR],
        timezone="America/New_York",
    )
    assert schedule.execution_mode is ScheduleExecutionMode.EMBEDDED
    assert schedule.misfire_policy is MisfirePolicy.COALESCE


def test_schedule_valid_construction_interval() -> None:
    schedule = Schedule(
        operation=RunOperation.EVIDENCE,
        frequency=ScheduleFrequency.INTERVAL,
        interval_hours=6,
        timezone="UTC",
    )
    assert schedule.interval_hours == 6


def test_schedule_weekly_requires_days_of_week() -> None:
    with pytest.raises(ValidationError, match="days_of_week is required"):
        Schedule(
            operation=RunOperation.REFRESH,
            frequency=ScheduleFrequency.WEEKLY,
            time_of_day=time(8, 0),
            timezone="UTC",
        )


def test_schedule_daily_requires_time_of_day() -> None:
    with pytest.raises(ValidationError, match="time_of_day is required"):
        Schedule(
            operation=RunOperation.REFRESH,
            frequency=ScheduleFrequency.DAILY,
            timezone="UTC",
        )


def test_schedule_interval_requires_interval_hours() -> None:
    with pytest.raises(ValidationError, match="interval_hours is required"):
        Schedule(
            operation=RunOperation.REFRESH,
            frequency=ScheduleFrequency.INTERVAL,
            timezone="UTC",
        )


def test_schedule_rejects_unknown_timezone() -> None:
    with pytest.raises(ValidationError, match="unknown IANA timezone"):
        Schedule(
            operation=RunOperation.REFRESH,
            frequency=ScheduleFrequency.INTERVAL,
            interval_hours=1,
            timezone="Not/AZone",
        )


# --- Notification ------------------------------------------------------


def test_notification_valid_construction() -> None:
    notification = Notification(
        run_id=uuid4(),
        category=NotificationCategory.ACTIONABLE,
        reason="awaiting_approval",
    )
    assert notification.dismissed_at is None


def test_notification_requires_a_subject_reference() -> None:
    with pytest.raises(ValidationError, match="at least one of"):
        Notification(category=NotificationCategory.INFORMATIONAL, reason="health_finding")


def test_notification_actionable_cannot_be_dismissed() -> None:
    with pytest.raises(ValidationError, match="not meaningful for actionable"):
        Notification(
            run_id=uuid4(),
            category=NotificationCategory.ACTIONABLE,
            reason="awaiting_approval",
            dismissed_at=datetime.now(UTC),
        )


def test_notification_informational_can_be_dismissed() -> None:
    notification = Notification(
        track_id=uuid4(),
        category=NotificationCategory.INFORMATIONAL,
        reason="refresh_completed",
        dismissed_at=datetime.now(UTC),
    )
    assert notification.dismissed_at is not None


# --- Enum JSON round-trips --------------------------------------------------


def test_track_json_round_trip_preserves_enum_values() -> None:
    track = Track(
        slug="ship-v2",
        title="Ship v2",
        type=TrackType.DELIVERABLE,
        priority=Priority.P0,
        status=TrackStatus.PAUSED,
        due_at=datetime(2026, 12, 1, tzinfo=UTC),
    )
    payload = json.loads(track.model_dump_json())
    assert payload["type"] == "deliverable"
    assert payload["status"] == "paused"
    assert payload["automation_mode"] == "proposal"

    restored = Track.model_validate(payload)
    assert restored == track


def test_run_json_round_trip_preserves_enum_values() -> None:
    run = Run(
        operation=RunOperation.CONDENSE,
        trigger=RunTrigger.WEB,
        status=RunStatus.AWAITING_DECISION,
        automation_mode=AutomationMode.PROPOSAL,
    )
    payload = json.loads(run.model_dump_json())
    assert payload["operation"] == "condense"
    assert payload["status"] == "awaiting_decision"
    assert payload["outcome"] is None

    restored = Run.model_validate(payload)
    assert restored == run
