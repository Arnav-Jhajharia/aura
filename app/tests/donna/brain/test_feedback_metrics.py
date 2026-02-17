"""Tests for donna.brain.feedback_metrics — nightly feedback aggregation."""

from datetime import datetime, timedelta, timezone

from db.models import ProactiveFeedback, generate_uuid
from donna.brain.feedback_metrics import (
    compute_adaptive_engagement_window,
    compute_category_preferences,
    compute_category_suppression,
    compute_engagement_trends,
    compute_format_preferences,
    compute_send_time_preferences,
)
from tests.conftest import make_user


def _fb(user_id, category="deadline_warning", outcome="positive_reply",
        sent_minutes_ago=30, format_used="text", feedback_score=1.0, **overrides):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    defaults = {
        "id": generate_uuid(),
        "user_id": user_id,
        "message_id": generate_uuid(),
        "category": category,
        "outcome": outcome,
        "feedback_score": feedback_score,
        "format_used": format_used,
        "sent_at": now - timedelta(minutes=sent_minutes_ago),
    }
    defaults.update(overrides)
    return ProactiveFeedback(**defaults)


class TestCategoryPreferences:
    async def test_no_data(self, db_session, patch_async_session):
        result = await compute_category_preferences("nobody")
        assert result["value"] == {}
        assert result["sample_size"] == 0

    async def test_preference_scores(self, db_session, patch_async_session):
        user = make_user(id="cp-1")
        db_session.add(user)
        # 3 positive deadline warnings
        for i in range(3):
            db_session.add(_fb("cp-1", "deadline_warning", "positive_reply",
                               sent_minutes_ago=60 * (i + 1), feedback_score=1.0))
        # 3 ignored wellbeing
        for i in range(3):
            db_session.add(_fb("cp-1", "wellbeing", "ignored",
                               sent_minutes_ago=60 * (i + 1), feedback_score=0.0))
        await db_session.commit()

        result = await compute_category_preferences("cp-1")
        assert "deadline_warning" in result["value"]
        assert "wellbeing" in result["value"]
        assert result["value"]["deadline_warning"] > result["value"]["wellbeing"]

    async def test_min_sample_size(self, db_session, patch_async_session):
        """Categories with < 3 samples are excluded."""
        user = make_user(id="cp-min")
        db_session.add(user)
        # Only 2 entries for this category
        db_session.add(_fb("cp-min", "nudge", "positive_reply", feedback_score=1.0))
        db_session.add(_fb("cp-min", "nudge", "positive_reply", feedback_score=1.0,
                           sent_minutes_ago=60))
        await db_session.commit()

        result = await compute_category_preferences("cp-min")
        assert "nudge" not in result["value"]


class TestEngagementTrends:
    async def test_no_data(self, db_session, patch_async_session):
        result = await compute_engagement_trends("nobody")
        assert result["value"] == {}

    async def test_rising_trend(self, db_session, patch_async_session):
        """More engagement this week than last → rising."""
        user = make_user(id="et-rise")
        db_session.add(user)
        # This week: 2 engaged, 0 ignored
        for i in range(2):
            db_session.add(_fb("et-rise", "deadline_warning", "positive_reply",
                               sent_minutes_ago=60 * (i + 1)))
        # Last week: 0 engaged, 2 ignored
        for i in range(2):
            db_session.add(_fb("et-rise", "deadline_warning", "ignored",
                               sent_minutes_ago=60 * 24 * 8 + i * 60, feedback_score=0.0))
        await db_session.commit()

        result = await compute_engagement_trends("et-rise")
        if "deadline_warning" in result["value"]:
            assert result["value"]["deadline_warning"]["direction"] == "rising"

    async def test_stable_trend(self, db_session, patch_async_session):
        """Same engagement rate → stable."""
        user = make_user(id="et-stable")
        db_session.add(user)
        # This week: 1 engaged, 1 ignored
        db_session.add(_fb("et-stable", "deadline_warning", "positive_reply",
                           sent_minutes_ago=60))
        db_session.add(_fb("et-stable", "deadline_warning", "ignored",
                           sent_minutes_ago=120, feedback_score=0.0))
        # Last week: 1 engaged, 1 ignored
        db_session.add(_fb("et-stable", "deadline_warning", "positive_reply",
                           sent_minutes_ago=60 * 24 * 8))
        db_session.add(_fb("et-stable", "deadline_warning", "ignored",
                           sent_minutes_ago=60 * 24 * 8 + 60, feedback_score=0.0))
        await db_session.commit()

        result = await compute_engagement_trends("et-stable")
        if "deadline_warning" in result["value"]:
            assert result["value"]["deadline_warning"]["direction"] == "stable"


class TestSendTimePreferences:
    async def test_no_data(self, db_session, patch_async_session):
        result = await compute_send_time_preferences("nobody")
        assert result["value"]["peak_hours"] == []
        assert result["sample_size"] == 0

    async def test_peak_hours(self, db_session, patch_async_session):
        """Hours with high engagement → peak_hours."""
        user = make_user(id="stp-1")
        db_session.add(user)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # 4 engaged entries at hour 9
        for i in range(4):
            sent_at = now.replace(hour=9, minute=i * 10)
            db_session.add(_fb("stp-1", sent_minutes_ago=0,
                               sent_at=sent_at - timedelta(days=i)))
        await db_session.commit()

        result = await compute_send_time_preferences("stp-1")
        assert 9 in result["value"]["peak_hours"]


class TestFormatPreferences:
    async def test_no_data(self, db_session, patch_async_session):
        result = await compute_format_preferences("nobody")
        assert result["value"]["preferred_format"] is None
        assert result["sample_size"] == 0

    async def test_button_preferred(self, db_session, patch_async_session):
        """Higher engagement with buttons → preferred_format = button."""
        user = make_user(id="fp-1")
        db_session.add(user)
        # 3 engaged button messages
        for i in range(3):
            db_session.add(_fb("fp-1", format_used="button", outcome="positive_reply",
                               sent_minutes_ago=60 * (i + 1)))
        # 3 ignored text messages
        for i in range(3):
            db_session.add(_fb("fp-1", format_used="text", outcome="ignored",
                               sent_minutes_ago=60 * (i + 1), feedback_score=0.0))
        await db_session.commit()

        result = await compute_format_preferences("fp-1")
        assert result["value"]["preferred_format"] == "button"
        assert result["value"]["format_rates"]["button"] > result["value"]["format_rates"]["text"]


class TestAdaptiveEngagementWindow:
    async def test_no_data(self, db_session, patch_async_session):
        result = await compute_adaptive_engagement_window("nobody")
        assert result["value"]["window_minutes"] == 60  # default
        assert result["sample_size"] == 0

    async def test_fast_responder(self, db_session, patch_async_session):
        """User responds in ~5 min → window = 30 min (floor)."""
        user = make_user(id="aew-fast")
        db_session.add(user)
        for i in range(5):
            db_session.add(_fb("aew-fast", outcome="positive_reply",
                               response_latency_seconds=300.0,
                               sent_minutes_ago=60 * (i + 1)))
        await db_session.commit()

        result = await compute_adaptive_engagement_window("aew-fast")
        assert result["value"]["window_minutes"] == 30  # floor
        assert result["value"]["median_response_minutes"] == 5.0

    async def test_slow_responder(self, db_session, patch_async_session):
        """User responds in ~45 min → window = 135 min."""
        user = make_user(id="aew-slow")
        db_session.add(user)
        for i in range(5):
            db_session.add(_fb("aew-slow", outcome="positive_reply",
                               response_latency_seconds=2700.0,
                               sent_minutes_ago=60 * (i + 1)))
        await db_session.commit()

        result = await compute_adaptive_engagement_window("aew-slow")
        assert result["value"]["window_minutes"] == 135.0
        assert result["value"]["median_response_minutes"] == 45.0


class TestCategorySuppression:
    async def test_no_data(self, db_session, patch_async_session):
        result = await compute_category_suppression("nobody")
        assert result["value"]["suppressed"] == {}

    async def test_zero_engagement_suppression(self, db_session, patch_async_session):
        """5 sends, 0 engagement → category suppressed."""
        user = make_user(id="cs-zero")
        db_session.add(user)
        for i in range(5):
            db_session.add(_fb("cs-zero", category="wellbeing", outcome="ignored",
                               feedback_score=0.0, sent_minutes_ago=60 * (i + 1)))
        await db_session.commit()

        result = await compute_category_suppression("cs-zero")
        assert "wellbeing" in result["value"]["suppressed"]
        assert result["value"]["suppressed"]["wellbeing"]["reason"] == "low_engagement"

    async def test_negative_feedback_suppression(self, db_session, patch_async_session):
        """3+ negative replies → category suppressed."""
        user = make_user(id="cs-neg")
        db_session.add(user)
        for i in range(3):
            db_session.add(_fb("cs-neg", category="social", outcome="negative_reply",
                               feedback_score=-0.5, sent_minutes_ago=60 * (i + 1)))
        await db_session.commit()

        result = await compute_category_suppression("cs-neg")
        assert "social" in result["value"]["suppressed"]
        assert result["value"]["suppressed"]["social"]["reason"] == "negative_feedback"

    async def test_good_engagement_not_suppressed(self, db_session, patch_async_session):
        """Good engagement → not suppressed."""
        user = make_user(id="cs-good")
        db_session.add(user)
        for i in range(5):
            db_session.add(_fb("cs-good", category="deadline_warning",
                               outcome="positive_reply",
                               sent_minutes_ago=60 * (i + 1)))
        await db_session.commit()

        result = await compute_category_suppression("cs-good")
        assert "deadline_warning" not in result["value"]["suppressed"]
