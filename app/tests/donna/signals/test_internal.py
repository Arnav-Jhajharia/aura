"""Tests for donna.signals.internal — time-based and DB-derived signals."""

import unittest.mock as mock
from datetime import datetime, timedelta, timezone

import pytest

from donna.signals.base import SignalType
from donna.signals.internal import collect_internal_signals
from tests.conftest import make_chat_message, make_habit, make_mood, make_task, make_user


@pytest.fixture
def user_id():
    return "test-user-internal"


async def test_morning_window_signal(db_session, patch_async_session, user_id):
    """At 8am (user wakes at 8), should emit TIME_MORNING_WINDOW."""
    user = make_user(id=user_id, wake_time="08:00", sleep_time="23:00")
    db_session.add(user)
    await db_session.commit()

    fake_now = datetime(2025, 6, 15, 8, 30, tzinfo=timezone.utc)
    with mock.patch("donna.signals.internal.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        signals = await collect_internal_signals(user_id)

    types = [s.type for s in signals]
    assert SignalType.TIME_MORNING_WINDOW in types


async def test_evening_window_signal(db_session, patch_async_session, user_id):
    """At 23:00 (user sleeps at 23), should emit TIME_EVENING_WINDOW."""
    user = make_user(id=user_id, sleep_time="23:00")
    db_session.add(user)
    await db_session.commit()

    fake_now = datetime(2025, 6, 15, 23, 0, tzinfo=timezone.utc)
    with mock.patch("donna.signals.internal.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        signals = await collect_internal_signals(user_id)

    types = [s.type for s in signals]
    assert SignalType.TIME_EVENING_WINDOW in types


async def test_overdue_task_signal(db_session, patch_async_session, user_id):
    """Task past due date should emit TASK_OVERDUE."""
    user = make_user(id=user_id)
    overdue_task = make_task(
        user_id=user_id, title="SE homework",
        due_date=datetime(2025, 6, 14, 12, 0),
    )
    db_session.add_all([user, overdue_task])
    await db_session.commit()

    fake_now = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
    with mock.patch("donna.signals.internal.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        signals = await collect_internal_signals(user_id)

    overdue = [s for s in signals if s.type == SignalType.TASK_OVERDUE]
    assert len(overdue) >= 1
    assert overdue[0].data["title"] == "SE homework"
    assert overdue[0].data["hours_overdue"] > 0


async def test_task_due_today_signal(db_session, patch_async_session, user_id):
    """Task due later today should emit TASK_DUE_TODAY."""
    user = make_user(id=user_id)
    task = make_task(
        user_id=user_id, title="Submit report",
        due_date=datetime(2025, 6, 15, 23, 59),
    )
    db_session.add_all([user, task])
    await db_session.commit()

    fake_now = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
    with mock.patch("donna.signals.internal.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        signals = await collect_internal_signals(user_id)

    due_today = [s for s in signals if s.type == SignalType.TASK_DUE_TODAY]
    assert len(due_today) >= 1
    assert due_today[0].data["title"] == "Submit report"


async def test_mood_trend_down(db_session, patch_async_session, user_id):
    """3 recent moods [3,2,4] with overall avg 6 should emit MOOD_TREND_DOWN."""
    user = make_user(id=user_id)
    db_session.add(user)

    now = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
    # Older high moods to bring up overall avg
    for i, score in enumerate([7, 8, 7, 6, 7]):
        db_session.add(make_mood(
            user_id=user_id, score=score,
            created_at=now - timedelta(days=6 - i),
        ))
    # Recent low moods
    for i, score in enumerate([3, 2, 4]):
        db_session.add(make_mood(
            user_id=user_id, score=score,
            created_at=now - timedelta(hours=3 - i),
        ))
    await db_session.commit()

    with mock.patch("donna.signals.internal.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        signals = await collect_internal_signals(user_id)

    types = [s.type for s in signals]
    assert SignalType.MOOD_TREND_DOWN in types


async def test_time_since_last_interaction(db_session, patch_async_session, user_id):
    """If user hasn't messaged in 8+ hours, emit TIME_SINCE_LAST_INTERACTION."""
    user = make_user(id=user_id)
    msg = make_chat_message(
        user_id=user_id, role="user", content="hey",
        created_at=datetime(2025, 6, 15, 6, 0),
    )
    db_session.add_all([user, msg])
    await db_session.commit()

    fake_now = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
    with mock.patch("donna.signals.internal.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        signals = await collect_internal_signals(user_id)

    interaction = [s for s in signals if s.type == SignalType.TIME_SINCE_LAST_INTERACTION]
    assert len(interaction) == 1
    assert interaction[0].data["hours_since"] >= 6


async def test_habit_streak_at_risk(db_session, patch_async_session, user_id):
    """Daily habit not logged in 22 hours should emit HABIT_STREAK_AT_RISK."""
    user = make_user(id=user_id)
    now = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
    habit = make_habit(
        user_id=user_id, name="Gym",
        target_frequency="daily",
        last_logged=now - timedelta(hours=22),
    )
    db_session.add_all([user, habit])
    await db_session.commit()

    with mock.patch("donna.signals.internal.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        signals = await collect_internal_signals(user_id)

    risk = [s for s in signals if s.type == SignalType.HABIT_STREAK_AT_RISK]
    assert len(risk) == 1
    assert risk[0].data["habit_name"] == "Gym"


async def test_no_signals_for_missing_user(patch_async_session):
    """Non-existent user should return empty."""
    signals = await collect_internal_signals("no-such-user")
    assert signals == []
