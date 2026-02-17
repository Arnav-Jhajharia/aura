"""Tests for donna.brain.prefilter — hard rules applied before LLM."""

import unittest.mock as mock
from datetime import datetime, timedelta, timezone

from donna.brain.prefilter import prefilter_signals
from donna.signals.base import Signal, SignalType
from tests.conftest import make_chat_message, make_user

# Mock trust to "established" so min_urgency=5 doesn't interfere with hard-rule tests
_ESTABLISHED_TRUST = {
    "level": "established",
    "days_active": 60,
    "total_interactions": 200,
    "score_threshold": 5.5,
    "daily_cap": 4,
    "min_urgency": 5,
}


def _patch_trust():
    return mock.patch(
        "donna.brain.prefilter.compute_trust_level",
        return_value=_ESTABLISHED_TRUST,
    )


def _signal(user_id="u1", stype=SignalType.CALENDAR_GAP_DETECTED, data=None):
    return Signal(type=stype, user_id=user_id, data=data or {})


def _urgent_signal(user_id="u1"):
    """Signal with urgency_hint >= 8 (CANVAS_DEADLINE_APPROACHING)."""
    return Signal(
        type=SignalType.CANVAS_DEADLINE_APPROACHING,
        user_id=user_id,
        data={"hours_until_due": 2},
    )


def _patch_local_hour(hour: int):
    return mock.patch("donna.brain.prefilter._get_local_hour", return_value=hour)


class TestQuietHours:
    async def test_quiet_hours_blocks(self, db_session, patch_async_session):
        """2am with non-urgent signals → should_continue=False."""
        user = make_user(id="pf-quiet")
        db_session.add(user)
        await db_session.commit()

        signals = [_signal("pf-quiet")]
        with _patch_local_hour(2), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-quiet", signals)

        assert should_continue is False
        assert filtered == []
        assert reason == "quiet_hours"

    async def test_quiet_hours_allows_urgent(self, db_session, patch_async_session):
        """2am with urgent signal (urgency_hint >= 8) → should_continue=True."""
        user = make_user(id="pf-urgent")
        db_session.add(user)
        await db_session.commit()

        signals = [_urgent_signal("pf-urgent")]
        with _patch_local_hour(2), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-urgent", signals)

        assert should_continue is True
        assert len(filtered) == 1
        assert reason is None

    async def test_daytime_passes(self, db_session, patch_async_session):
        """2pm (daytime) → quiet hours don't block."""
        user = make_user(id="pf-day")
        db_session.add(user)
        await db_session.commit()

        signals = [_signal("pf-day")]
        with _patch_local_hour(14), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-day", signals)

        assert should_continue is True
        assert len(filtered) == 1
        assert reason is None

    async def test_quiet_hours_returns_reason(self, db_session, patch_async_session):
        """Quiet hours block returns 'quiet_hours' as reason."""
        user = make_user(id="pf-qr")
        db_session.add(user)
        await db_session.commit()

        signals = [_signal("pf-qr")]
        with _patch_local_hour(2), _patch_trust():
            _, should_continue, _, reason = await prefilter_signals("pf-qr", signals)

        assert should_continue is False
        assert reason == "quiet_hours"


class TestDailyCap:
    async def test_daily_cap_blocks(self, db_session, patch_async_session):
        """At daily cap (4 messages sent today) → should_continue=False."""
        user = make_user(id="pf-cap")
        db_session.add(user)
        # Add 4 proactive messages today (use minute offsets to stay within today UTC)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(4):
            msg = make_chat_message(
                user_id="pf-cap", role="assistant",
                content=f"proactive {i}",
                created_at=now - timedelta(minutes=i + 1),
            )
            msg.is_proactive = True
            db_session.add(msg)
        await db_session.commit()

        signals = [_signal("pf-cap")]
        with _patch_local_hour(14), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-cap", signals)

        assert should_continue is False
        assert reason == "daily_cap"

    async def test_under_cap_passes(self, db_session, patch_async_session):
        """Under daily cap → should_continue=True."""
        user = make_user(id="pf-cap-ok")
        db_session.add(user)
        await db_session.commit()

        signals = [_signal("pf-cap-ok")]
        with _patch_local_hour(14), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-cap-ok", signals)

        assert should_continue is True
        assert reason is None


class TestCooldown:
    async def test_cooldown_blocks_recent(self, db_session, patch_async_session):
        """Proactive message sent 10 min ago → should_continue=False."""
        user = make_user(id="pf-cool")
        recent = make_chat_message(
            user_id="pf-cool", role="assistant",
            content="recent proactive",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        recent.is_proactive = True
        db_session.add_all([user, recent])
        await db_session.commit()

        signals = [_signal("pf-cool")]
        with _patch_local_hour(14), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-cool", signals)

        assert should_continue is False
        assert reason == "cooldown"

    async def test_cooldown_passed(self, db_session, patch_async_session):
        """Proactive message 45 min ago → should_continue=True."""
        user = make_user(id="pf-cool-ok")
        old_msg = make_chat_message(
            user_id="pf-cool-ok", role="assistant",
            content="old proactive",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=45),
        )
        old_msg.is_proactive = True
        db_session.add_all([user, old_msg])
        await db_session.commit()

        signals = [_signal("pf-cool-ok")]
        with _patch_local_hour(14), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-cool-ok", signals)

        assert should_continue is True
        assert reason is None

    async def test_urgent_bypasses_cooldown(self, db_session, patch_async_session):
        """Urgent signal bypasses cooldown."""
        user = make_user(id="pf-urg-cool")
        recent = make_chat_message(
            user_id="pf-urg-cool", role="assistant",
            content="recent msg",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        recent.is_proactive = True
        db_session.add_all([user, recent])
        await db_session.commit()

        signals = [_urgent_signal("pf-urg-cool")]
        with _patch_local_hour(14), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-urg-cool", signals)

        assert should_continue is True
        assert reason is None


class TestAllPass:
    async def test_all_rules_pass(self, db_session, patch_async_session):
        """When all rules pass, signals returned unchanged."""
        user = make_user(id="pf-pass")
        db_session.add(user)
        await db_session.commit()

        signals = [_signal("pf-pass"), _signal("pf-pass")]
        with _patch_local_hour(14), _patch_trust():
            filtered, should_continue, _trust, reason = await prefilter_signals("pf-pass", signals)

        assert should_continue is True
        assert len(filtered) == 2
        assert reason is None

    async def test_empty_signals(self, db_session, patch_async_session):
        """Empty signals list → should_continue=False."""
        filtered, should_continue, _trust, reason = await prefilter_signals("nobody", [])
        assert should_continue is False
        assert reason == "no_signals"

    async def test_trust_min_urgency_filters(self, db_session, patch_async_session):
        """New user (min_urgency=7) filters out low-urgency signals."""
        new_trust = {**_ESTABLISHED_TRUST, "level": "new", "min_urgency": 7}
        user = make_user(id="pf-trust")
        db_session.add(user)
        await db_session.commit()

        signals = [_signal("pf-trust")]  # urgency_hint=5, below min_urgency=7
        with (
            _patch_local_hour(14),
            mock.patch("donna.brain.prefilter.compute_trust_level", return_value=new_trust),
        ):
            filtered, should_continue, trust, reason = await prefilter_signals("pf-trust", signals)

        assert should_continue is False
        assert trust["level"] == "new"
        assert reason == "low_urgency"
