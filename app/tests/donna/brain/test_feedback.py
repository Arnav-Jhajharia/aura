"""Tests for donna.brain.feedback — proactive message feedback loop."""

from datetime import datetime, timedelta, timezone

from db.models import ProactiveFeedback, generate_uuid
from sqlalchemy import select as sa_select

from db.models import UserBehavior
from donna.brain.feedback import (
    OUTCOME_SCORES,
    apply_meta_feedback,
    check_and_update_feedback,
    classify_reply_sentiment,
    detect_meta_feedback,
    get_feedback_summary,
    is_explicit_stop,
    record_proactive_send,
)
from tests.conftest import make_user


def _make_feedback(user_id, outcome="pending", category="deadline_warning",
                   sent_minutes_ago=30, **overrides):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    defaults = {
        "id": generate_uuid(),
        "user_id": user_id,
        "message_id": generate_uuid(),
        "category": category,
        "trigger_signals": ["canvas_deadline_approaching"],
        "sent_at": now - timedelta(minutes=sent_minutes_ago),
        "outcome": outcome,
    }
    defaults.update(overrides)
    return ProactiveFeedback(**defaults)


class TestRecordProactiveSend:
    async def test_creates_feedback_entry(self, db_session, patch_async_session):
        user = make_user(id="fb-rec")
        db_session.add(user)
        await db_session.commit()

        candidate = {
            "message": "SE due Friday",
            "category": "deadline_warning",
            "trigger_signals": ["canvas_deadline_approaching"],
        }
        await record_proactive_send("fb-rec", "msg-123", candidate)

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.user_id == "fb-rec")
            )
            fb = result.scalar_one()
            assert fb.outcome == "pending"
            assert fb.category == "deadline_warning"
            assert fb.message_id == "msg-123"


class TestClassifyReplySentiment:
    def test_positive_thanks(self):
        assert classify_reply_sentiment("thanks!") == "positive"

    def test_positive_emoji(self):
        assert classify_reply_sentiment("👍") == "positive"

    def test_positive_helpful(self):
        assert classify_reply_sentiment("that's really helpful") == "positive"

    def test_negative_stop(self):
        assert classify_reply_sentiment("stop sending me these") == "negative"

    def test_negative_annoying(self):
        assert classify_reply_sentiment("this is annoying") == "negative"

    def test_negative_dont_text(self):
        assert classify_reply_sentiment("don't text me about this") == "negative"

    def test_neutral_ok(self):
        assert classify_reply_sentiment("ok") == "neutral"

    def test_neutral_empty(self):
        assert classify_reply_sentiment("") == "neutral"

    def test_neutral_none(self):
        assert classify_reply_sentiment(None) == "neutral"

    def test_neutral_task_response(self):
        assert classify_reply_sentiment("I'll work on it after lunch") == "neutral"


class TestIsExplicitStop:
    def test_stop_sending(self):
        assert is_explicit_stop("stop sending me messages") is True

    def test_dont_text_me(self):
        assert is_explicit_stop("don't text me about this") is True

    def test_leave_me_alone(self):
        assert is_explicit_stop("leave me alone") is True

    def test_not_a_stop(self):
        assert is_explicit_stop("thanks") is False

    def test_none(self):
        assert is_explicit_stop(None) is False


class TestCheckAndUpdateFeedback:
    async def test_positive_reply_within_window(self, db_session, patch_async_session):
        """Pending message + positive reply within window → positive_reply."""
        user = make_user(id="fb-pos")
        fb = _make_feedback("fb-pos", outcome="pending", sent_minutes_ago=30)
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-pos", reply_text="thanks!")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "positive_reply"
            assert updated.reply_sentiment == "positive"
            assert updated.feedback_score == 1.0
            assert updated.response_latency_seconds is not None

    async def test_negative_reply_within_window(self, db_session, patch_async_session):
        """Pending message + negative reply → negative_reply."""
        user = make_user(id="fb-neg")
        fb = _make_feedback("fb-neg", outcome="pending", sent_minutes_ago=20)
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-neg", reply_text="this is annoying")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "negative_reply"
            assert updated.reply_sentiment == "negative"
            assert updated.feedback_score == -0.5

    async def test_neutral_reply_within_window(self, db_session, patch_async_session):
        """Pending message + neutral reply → neutral_reply."""
        user = make_user(id="fb-neut")
        fb = _make_feedback("fb-neut", outcome="pending", sent_minutes_ago=15)
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-neut", reply_text="ok")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "neutral_reply"
            assert updated.feedback_score == 0.7

    async def test_no_reply_text_defaults_neutral(self, db_session, patch_async_session):
        """Pending message + no reply_text → neutral_reply (backward compat)."""
        user = make_user(id="fb-notext")
        fb = _make_feedback("fb-notext", outcome="pending", sent_minutes_ago=30)
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-notext")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "neutral_reply"

    async def test_explicit_stop(self, db_session, patch_async_session):
        """Explicit stop request → explicit_stop outcome."""
        user = make_user(id="fb-stop")
        fb = _make_feedback("fb-stop", outcome="pending", sent_minutes_ago=10)
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-stop", reply_text="stop sending me messages")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "explicit_stop"
            assert updated.feedback_score == -1.0

    async def test_late_engage(self, db_session, patch_async_session):
        """Reply between 60 and 180 min → late_engage."""
        user = make_user(id="fb-late")
        fb = _make_feedback("fb-late", outcome="pending", sent_minutes_ago=90)
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-late", reply_text="ok got it")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "late_engage"
            assert updated.feedback_score == 0.4

    async def test_times_out_old_as_ignored(self, db_session, patch_async_session):
        """Pending message sent 4 hours ago → ignored."""
        user = make_user(id="fb-ignore")
        fb = _make_feedback("fb-ignore", outcome="pending", sent_minutes_ago=240)
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-ignore")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "ignored"
            assert updated.feedback_score == 0.0

    async def test_undelivered_failed(self, db_session, patch_async_session):
        """Failed delivery + timed out → undelivered."""
        user = make_user(id="fb-undel")
        fb = _make_feedback("fb-undel", outcome="pending", sent_minutes_ago=240,
                            delivery_status="failed")
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-undel")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "undelivered"
            assert updated.feedback_score is None

    async def test_read_but_ignored(self, db_session, patch_async_session):
        """Read but no reply → ignored with score 0.0."""
        user = make_user(id="fb-read-ign")
        fb = _make_feedback("fb-read-ign", outcome="pending", sent_minutes_ago=240,
                            delivery_status="read")
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-read-ign")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "ignored"
            assert updated.feedback_score == 0.0

    async def test_delivered_but_not_read_ignored(self, db_session, patch_async_session):
        """Delivered but not read → ignored with delivered_only score."""
        user = make_user(id="fb-deliv-ign")
        fb = _make_feedback("fb-deliv-ign", outcome="pending", sent_minutes_ago=240,
                            delivery_status="delivered")
        db_session.add_all([user, fb])
        await db_session.commit()

        await check_and_update_feedback("fb-deliv-ign")

        from sqlalchemy import select
        async with patch_async_session() as session:
            result = await session.execute(
                select(ProactiveFeedback).where(ProactiveFeedback.id == fb.id)
            )
            updated = result.scalar_one()
            assert updated.outcome == "ignored"
            assert updated.feedback_score == OUTCOME_SCORES["delivered_only"]


class TestGetFeedbackSummary:
    async def test_empty_summary(self, db_session, patch_async_session):
        result = await get_feedback_summary("nobody")
        assert result["total_sent"] == 0
        assert result["engagement_rate"] == 0.0

    async def test_summary_with_data(self, db_session, patch_async_session):
        user = make_user(id="fb-sum")
        db_session.add(user)
        # positive_reply and neutral_reply count as engaged, ignored doesn't
        db_session.add(_make_feedback(
            "fb-sum", outcome="positive_reply", category="deadline_warning",
            response_latency_seconds=120.0,
        ))
        db_session.add(_make_feedback(
            "fb-sum", outcome="neutral_reply", category="deadline_warning",
            response_latency_seconds=60.0,
        ))
        db_session.add(_make_feedback(
            "fb-sum", outcome="ignored", category="wellbeing",
        ))
        await db_session.commit()

        result = await get_feedback_summary("fb-sum")
        assert result["total_sent"] == 3
        assert result["engaged"] == 2
        assert result["ignored"] == 1
        assert result["engagement_rate"] == 2 / 3
        assert result["engagement_by_category"]["deadline_warning"] == 1.0
        assert result["engagement_by_category"]["wellbeing"] == 0.0
        assert result["avg_response_latency_seconds"] == 90.0


class TestDetectMetaFeedback:
    def test_suppress_wellbeing(self):
        result = detect_meta_feedback("stop sending me wellbeing check-ins")
        assert any(r["action"] == "suppress" and r["target"] == "wellbeing" for r in result)

    def test_boost_deadline(self):
        result = detect_meta_feedback("the deadline reminders are really helpful")
        assert any(r["action"] == "boost" and r["target"] == "deadline_warning" for r in result)

    def test_format_preference_buttons(self):
        result = detect_meta_feedback("the buttons are really useful")
        assert any(r["action"] == "format_pref" and r["target"] == "button" for r in result)

    def test_time_preference_morning(self):
        result = detect_meta_feedback("can you text me in the morning")
        assert any(r["action"] == "time_adjust" for r in result)

    def test_no_meta_feedback(self):
        result = detect_meta_feedback("I'll work on the assignment later")
        assert result == []

    def test_empty_text(self):
        assert detect_meta_feedback("") == []
        assert detect_meta_feedback(None) == []

    def test_too_many_messages(self):
        result = detect_meta_feedback("you send too many messages")
        assert any(r["action"] == "reduce_frequency" for r in result)


class TestApplyMetaFeedback:
    async def test_suppress_creates_behavior(self, db_session, patch_async_session):
        """Suppress meta-feedback creates category_suppression UserBehavior."""
        user = make_user(id="meta-sup")
        db_session.add(user)
        await db_session.commit()

        meta = [{"action": "suppress", "target": "wellbeing", "pattern": "test"}]
        await apply_meta_feedback("meta-sup", meta)

        async with patch_async_session() as session:
            result = await session.execute(
                sa_select(UserBehavior).where(
                    UserBehavior.user_id == "meta-sup",
                    UserBehavior.behavior_key == "category_suppression",
                )
            )
            behavior = result.scalar_one()
            assert "wellbeing" in behavior.value["suppressed"]
            assert behavior.value["suppressed"]["wellbeing"]["reason"] == "explicit_stop"
            assert behavior.confidence == 1.0

    async def test_boost_creates_override(self, db_session, patch_async_session):
        """Boost meta-feedback creates meta_category_overrides."""
        user = make_user(id="meta-boost")
        db_session.add(user)
        await db_session.commit()

        meta = [{"action": "boost", "target": "deadline_warning", "pattern": "test"}]
        await apply_meta_feedback("meta-boost", meta)

        async with patch_async_session() as session:
            result = await session.execute(
                sa_select(UserBehavior).where(
                    UserBehavior.user_id == "meta-boost",
                    UserBehavior.behavior_key == "meta_category_overrides",
                )
            )
            behavior = result.scalar_one()
            assert behavior.value["deadline_warning"]["boost"] is True

    async def test_format_pref_stores(self, db_session, patch_async_session):
        """Format preference meta-feedback stores correctly."""
        user = make_user(id="meta-fmt")
        db_session.add(user)
        await db_session.commit()

        meta = [{"action": "format_pref", "target": "button", "pattern": "test"}]
        await apply_meta_feedback("meta-fmt", meta)

        async with patch_async_session() as session:
            result = await session.execute(
                sa_select(UserBehavior).where(
                    UserBehavior.user_id == "meta-fmt",
                    UserBehavior.behavior_key == "meta_format_preference",
                )
            )
            behavior = result.scalar_one()
            assert behavior.value["preferred_format"] == "button"

    async def test_empty_signals_noop(self, db_session, patch_async_session):
        """Empty signals list does nothing."""
        await apply_meta_feedback("nobody", [])  # No error
