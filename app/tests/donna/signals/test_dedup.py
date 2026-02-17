"""Tests for donna.signals.dedup — signal deduplication."""

import pytest

from donna.signals.base import Signal, SignalType
from donna.signals.dedup import deduplicate_signals
from tests.conftest import make_user


@pytest.fixture
def user_id():
    return "test-user-dedup"


async def test_new_signal_passes(db_session, patch_async_session, user_id):
    """A signal seen for the first time should pass through."""
    user = make_user(id=user_id)
    db_session.add(user)
    await db_session.commit()

    sig = Signal(
        type=SignalType.TASK_OVERDUE,
        user_id=user_id,
        data={"title": "SE homework"},
        source="internal",
    )
    result = await deduplicate_signals(user_id, [sig])
    assert len(result) == 1
    assert result[0].type == SignalType.TASK_OVERDUE


async def test_duplicate_signal_blocked(db_session, patch_async_session, user_id):
    """Same signal in consecutive cycles should be blocked."""
    user = make_user(id=user_id)
    db_session.add(user)
    await db_session.commit()

    sig1 = Signal(
        type=SignalType.TASK_OVERDUE,
        user_id=user_id,
        data={"title": "SE homework"},
        source="internal",
    )
    sig2 = Signal(
        type=SignalType.TASK_OVERDUE,
        user_id=user_id,
        data={"title": "SE homework"},
        source="internal",
    )

    # First pass — should emit
    result1 = await deduplicate_signals(user_id, [sig1])
    assert len(result1) == 1

    # Second pass — should be blocked (too soon to re-emit)
    result2 = await deduplicate_signals(user_id, [sig2])
    assert len(result2) == 0


async def test_email_dedup_by_id(db_session, patch_async_session, user_id):
    """Different email IDs should pass; same ID should be blocked."""
    user = make_user(id=user_id)
    db_session.add(user)
    await db_session.commit()

    email_a = Signal(
        type=SignalType.EMAIL_IMPORTANT_RECEIVED,
        user_id=user_id,
        data={"id": "msg-001", "subject": "Offer letter"},
        source="gmail",
    )
    email_b = Signal(
        type=SignalType.EMAIL_IMPORTANT_RECEIVED,
        user_id=user_id,
        data={"id": "msg-002", "subject": "Meeting notes"},
        source="gmail",
    )
    email_a_dup = Signal(
        type=SignalType.EMAIL_IMPORTANT_RECEIVED,
        user_id=user_id,
        data={"id": "msg-001", "subject": "Offer letter"},
        source="gmail",
    )

    # Both distinct emails pass on first cycle
    result1 = await deduplicate_signals(user_id, [email_a, email_b])
    assert len(result1) == 2

    # Re-sending email_a should be blocked; email_b also blocked
    result2 = await deduplicate_signals(user_id, [email_a_dup])
    assert len(result2) == 0


async def test_morning_window_once_per_day(db_session, patch_async_session, user_id):
    """Time-window signals use daily key — same day blocked."""
    user = make_user(id=user_id)
    db_session.add(user)
    await db_session.commit()

    sig1 = Signal(
        type=SignalType.TIME_MORNING_WINDOW,
        user_id=user_id,
        data={"wake_time": "08:00", "user_name": "Test"},
        source="internal",
    )
    sig2 = Signal(
        type=SignalType.TIME_MORNING_WINDOW,
        user_id=user_id,
        data={"wake_time": "08:00", "user_name": "Test"},
        source="internal",
    )

    result1 = await deduplicate_signals(user_id, [sig1])
    assert len(result1) == 1

    result2 = await deduplicate_signals(user_id, [sig2])
    assert len(result2) == 0


async def test_empty_list(db_session, patch_async_session, user_id):
    """Empty input should return empty output."""
    result = await deduplicate_signals(user_id, [])
    assert result == []
