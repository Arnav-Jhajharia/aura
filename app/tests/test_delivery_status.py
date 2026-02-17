"""Tests for delivery status tracking via webhook status updates."""

from datetime import datetime, timezone

from api.webhook import _handle_status_update
from db.models import ProactiveFeedback, generate_uuid


class TestDeliveryStatus:
    async def test_delivered_updates_status(self, db_session, patch_async_session):
        """WhatsApp 'delivered' status → updates delivery_status."""
        fb = ProactiveFeedback(
            id=generate_uuid(), user_id="u1", message_id="m1",
            wa_message_id="wamid.abc", delivery_status="sent",
            sent_at=datetime.now(timezone.utc),
        )
        db_session.add(fb)
        await db_session.commit()

        await _handle_status_update({"id": "wamid.abc", "status": "delivered"})

        await db_session.refresh(fb)
        assert fb.delivery_status == "delivered"

    async def test_read_after_delivered(self, db_session, patch_async_session):
        """delivered → read advances the status."""
        fb = ProactiveFeedback(
            id=generate_uuid(), user_id="u1", message_id="m2",
            wa_message_id="wamid.read", delivery_status="delivered",
            sent_at=datetime.now(timezone.utc),
        )
        db_session.add(fb)
        await db_session.commit()

        await _handle_status_update({"id": "wamid.read", "status": "read"})

        await db_session.refresh(fb)
        assert fb.delivery_status == "read"

    async def test_delivered_after_read_no_regression(self, db_session, patch_async_session):
        """read → delivered should NOT regress the status."""
        fb = ProactiveFeedback(
            id=generate_uuid(), user_id="u1", message_id="m3",
            wa_message_id="wamid.noreg", delivery_status="read",
            sent_at=datetime.now(timezone.utc),
        )
        db_session.add(fb)
        await db_session.commit()

        await _handle_status_update({"id": "wamid.noreg", "status": "delivered"})

        await db_session.refresh(fb)
        assert fb.delivery_status == "read"  # stays at read

    async def test_failed_with_error(self, db_session, patch_async_session):
        """Failed status stores the error info."""
        fb = ProactiveFeedback(
            id=generate_uuid(), user_id="u1", message_id="m4",
            wa_message_id="wamid.fail", delivery_status="sent",
            sent_at=datetime.now(timezone.utc),
        )
        db_session.add(fb)
        await db_session.commit()

        await _handle_status_update({
            "id": "wamid.fail",
            "status": "failed",
            "errors": [{"code": 131047, "title": "Message expired"}],
        })

        await db_session.refresh(fb)
        assert fb.delivery_status == "failed"
        assert "131047" in fb.delivery_failed_reason

    async def test_unknown_wa_message_id_no_crash(self, db_session, patch_async_session):
        """Unknown wa_message_id → no crash, just returns."""
        await _handle_status_update({"id": "wamid.unknown", "status": "delivered"})
        # No exception = pass
