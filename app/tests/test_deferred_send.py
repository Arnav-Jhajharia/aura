"""Tests for deferred send processing (agent/scheduler.py)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from agent.scheduler import _is_stale, process_deferred_sends
from db.models import DeferredSend, generate_uuid
from tests.conftest import make_user


class TestProcessDeferredSends:
    async def test_due_message_sent(self, db_session, patch_async_session):
        """Due deferred send → sent and marked attempted."""
        user = make_user(id="ds-due")
        db_session.add(user)
        ds = DeferredSend(
            id=generate_uuid(), user_id="ds-due",
            candidate_json={"message": "Hey there", "category": "nudge"},
            block_reason="quiet_hours",
            scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db_session.add(ds)
        await db_session.commit()

        with patch("agent.scheduler.send_proactive_message",
                    new_callable=AsyncMock, return_value=True):
            await process_deferred_sends()

        await db_session.refresh(ds)
        assert ds.attempted is True

    async def test_future_not_touched(self, db_session, patch_async_session):
        """Future scheduled_for → not processed."""
        user = make_user(id="ds-future")
        db_session.add(user)
        ds = DeferredSend(
            id=generate_uuid(), user_id="ds-future",
            candidate_json={"message": "Later", "category": "nudge"},
            block_reason="quiet_hours",
            scheduled_for=datetime.now(timezone.utc) + timedelta(hours=3),
        )
        db_session.add(ds)
        await db_session.commit()

        with patch("agent.scheduler.send_proactive_message",
                    new_callable=AsyncMock) as mock_send:
            await process_deferred_sends()

        mock_send.assert_not_called()
        await db_session.refresh(ds)
        assert ds.attempted is False

    async def test_stale_past_deadline_expired(self, db_session, patch_async_session):
        """Candidate with past deadline → expired, not sent."""
        user = make_user(id="ds-stale")
        db_session.add(user)
        ds = DeferredSend(
            id=generate_uuid(), user_id="ds-stale",
            candidate_json={
                "message": "Assignment due!",
                "category": "deadline_warning",
                "data": {"due_date": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
            },
            block_reason="quiet_hours",
            scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db_session.add(ds)
        await db_session.commit()

        with patch("agent.scheduler.send_proactive_message",
                    new_callable=AsyncMock) as mock_send:
            await process_deferred_sends()

        mock_send.assert_not_called()
        await db_session.refresh(ds)
        assert ds.expired is True

    async def test_already_attempted_skipped(self, db_session, patch_async_session):
        """Already attempted → skipped."""
        user = make_user(id="ds-done")
        db_session.add(user)
        ds = DeferredSend(
            id=generate_uuid(), user_id="ds-done",
            candidate_json={"message": "Old", "category": "nudge"},
            block_reason="quiet_hours",
            scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=5),
            attempted=True,
        )
        db_session.add(ds)
        await db_session.commit()

        with patch("agent.scheduler.send_proactive_message",
                    new_callable=AsyncMock) as mock_send:
            await process_deferred_sends()

        mock_send.assert_not_called()


class TestIsStaleness:
    def test_past_deadline_stale(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        candidate = {
            "data": {"due_date": (now - timedelta(hours=1)).isoformat()},
        }
        assert _is_stale(candidate, now) is True

    def test_future_deadline_not_stale(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        candidate = {
            "data": {"due_date": (now + timedelta(hours=5)).isoformat()},
        }
        assert _is_stale(candidate, now) is False

    def test_no_deadline_not_stale(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        candidate = {"message": "hello"}
        assert _is_stale(candidate, now) is False

    def test_old_created_at_stale(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        candidate = {
            "_created_at": (now - timedelta(hours=13)).isoformat(),
        }
        assert _is_stale(candidate, now) is True
