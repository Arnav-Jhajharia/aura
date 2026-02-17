"""Tests for donna.signals.enrichment — cross-signal enrichment."""

from donna.signals.base import Signal, SignalType
from donna.signals.enrichment import enrich_signals

USER = "test-user-enrich"


def test_gap_plus_deadline_enrichment():
    """Calendar gap + Canvas deadline → suggested_task annotation."""
    gap = Signal(
        type=SignalType.CALENDAR_GAP_DETECTED,
        user_id=USER,
        data={"start": "2025-06-15T14:00", "end": "2025-06-15T16:00", "duration_hours": 2.0},
        source="google_calendar",
    )
    deadline = Signal(
        type=SignalType.CANVAS_DEADLINE_APPROACHING,
        user_id=USER,
        data={
            "title": "CS2103T Quiz",
            "course": "Software Engineering",
            "hours_until": 5.0,
            "urgency_label": "12_hours",
        },
        source="canvas",
    )

    result = enrich_signals([gap, deadline])
    assert len(result) == 2
    assert result[0].data["suggested_task"] == "CS2103T Quiz"
    assert result[0].data["suggested_course"] == "Software Engineering"


def test_mood_plus_busy_enrichment():
    """Mood down + busy day → care_escalation flag."""
    mood = Signal(
        type=SignalType.MOOD_TREND_DOWN,
        user_id=USER,
        data={"recent_avg": 3.0, "overall_avg": 6.0, "last_score": 2, "days_tracked": 7},
        source="internal",
    )
    busy = Signal(
        type=SignalType.CALENDAR_BUSY_DAY,
        user_id=USER,
        data={"event_count": 6, "date": "2025-06-15"},
        source="google_calendar",
    )

    result = enrich_signals([mood, busy])
    assert result[0].data["care_escalation"] is True


def test_habit_plus_evening_enrichment():
    """Habit at risk + evening window → bedtime_reminder flag."""
    habit = Signal(
        type=SignalType.HABIT_STREAK_AT_RISK,
        user_id=USER,
        data={"habit_name": "Gym", "current_streak": 5, "hours_since_logged": 22.0},
        source="internal",
    )
    evening = Signal(
        type=SignalType.TIME_EVENING_WINDOW,
        user_id=USER,
        data={"sleep_time": "23:00", "user_name": "Test"},
        source="internal",
    )

    result = enrich_signals([habit, evening])
    assert result[0].data["bedtime_reminder"] is True


def test_no_enrichment_when_no_patterns():
    """Unrelated signals should pass through unchanged."""
    sig = Signal(
        type=SignalType.EMAIL_UNREAD_PILING,
        user_id=USER,
        data={"unread_count": 10, "subjects": ["a", "b"]},
        source="gmail",
    )

    result = enrich_signals([sig])
    assert len(result) == 1
    assert "suggested_task" not in result[0].data
    assert "care_escalation" not in result[0].data
    assert "bedtime_reminder" not in result[0].data
