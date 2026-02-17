"""Tests for donna.brain.trust — trust level computation."""

from datetime import datetime, timedelta, timezone

from donna.brain.trust import compute_trust_level
from tests.conftest import make_chat_message, make_user


class TestTrustLevels:
    async def test_new_user_by_days(self, db_session, patch_async_session):
        """User created 5 days ago with few messages → new."""
        user = make_user(
            id="trust-new",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5),
        )
        db_session.add(user)
        await db_session.commit()

        result = await compute_trust_level("trust-new")
        assert result["level"] == "new"
        assert result["daily_cap"] == 2
        assert result["score_threshold"] == 7.0

    async def test_new_user_by_messages(self, db_session, patch_async_session):
        """User created 20 days ago but only 10 messages → new (< 20 msgs)."""
        user = make_user(
            id="trust-new-msg",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=20),
        )
        db_session.add(user)
        for i in range(10):
            db_session.add(make_chat_message("trust-new-msg", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-new-msg")
        assert result["level"] == "new"

    async def test_building_level(self, db_session, patch_async_session):
        """User 20 days, 25 messages → building."""
        user = make_user(
            id="trust-build",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=20),
        )
        db_session.add(user)
        for i in range(25):
            db_session.add(make_chat_message("trust-build", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-build")
        assert result["level"] == "building"
        assert result["daily_cap"] == 3
        assert result["score_threshold"] == 6.0

    async def test_established_level(self, db_session, patch_async_session):
        """User 45 days, 150 messages → established."""
        user = make_user(
            id="trust-est",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=45),
        )
        db_session.add(user)
        for i in range(150):
            db_session.add(make_chat_message("trust-est", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-est")
        assert result["level"] == "established"
        assert result["daily_cap"] == 4
        assert result["score_threshold"] == 5.5

    async def test_deep_level(self, db_session, patch_async_session):
        """User 100 days, 200 messages → deep."""
        user = make_user(
            id="trust-deep",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=100),
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-deep", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-deep")
        assert result["level"] == "deep"
        assert result["daily_cap"] == 5
        assert result["score_threshold"] == 5.0

    async def test_missing_user(self, db_session, patch_async_session):
        """Non-existent user → defaults to new."""
        result = await compute_trust_level("nonexistent")
        assert result["level"] == "new"
        assert result["days_active"] == 0

    async def test_boundary_14_days_20_msgs(self, db_session, patch_async_session):
        """Exactly 14 days and 20 messages → building (not new)."""
        user = make_user(
            id="trust-boundary",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=14),
        )
        db_session.add(user)
        for i in range(20):
            db_session.add(
                make_chat_message("trust-boundary", role="user", content=f"msg {i}")
            )
        await db_session.commit()

        result = await compute_trust_level("trust-boundary")
        assert result["level"] == "building"


class TestTrustDeescalation:
    async def test_deep_demoted_to_established_after_30_days(self, db_session, patch_async_session):
        """Deep trust user inactive 35 days → established."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-deesc-30",
            created_at=now - timedelta(days=100),
            last_active_at=now - timedelta(days=35),
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-deesc-30", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-deesc-30")
        assert result["level"] == "established"
        assert result["score_threshold"] == 5.5

    async def test_deep_demoted_to_building_after_60_days(self, db_session, patch_async_session):
        """Deep trust user inactive 65 days → building (demoted 2 levels)."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-deesc-60",
            created_at=now - timedelta(days=120),
            last_active_at=now - timedelta(days=65),
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-deesc-60", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-deesc-60")
        assert result["level"] == "building"
        assert result["score_threshold"] == 6.0

    async def test_no_demotion_when_active(self, db_session, patch_async_session):
        """Deep trust user active recently → stays deep."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-active",
            created_at=now - timedelta(days=100),
            last_active_at=now - timedelta(days=2),
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-active", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-active")
        assert result["level"] == "deep"

    async def test_demotion_floors_at_new(self, db_session, patch_async_session):
        """Building user inactive 60+ days → floors at new."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-floor",
            created_at=now - timedelta(days=25),
            last_active_at=now - timedelta(days=65),
        )
        db_session.add(user)
        for i in range(25):
            db_session.add(make_chat_message("trust-floor", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-floor")
        assert result["level"] == "new"

    async def test_no_demotion_without_last_active(self, db_session, patch_async_session):
        """User with no last_active_at → no demotion applied."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-no-active",
            created_at=now - timedelta(days=100),
            last_active_at=None,
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-no-active", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-no-active")
        assert result["level"] == "deep"


class TestTrustDeEscalation:
    async def test_deep_demoted_after_30_days_inactive(self, db_session, patch_async_session):
        """Deep user with 30+ days inactive → established."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-demote-30",
            created_at=now - timedelta(days=120),
            last_active_at=now - timedelta(days=35),
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-demote-30", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-demote-30")
        assert result["level"] == "established"
        assert result["daily_cap"] == 4

    async def test_deep_demoted_after_60_days_inactive(self, db_session, patch_async_session):
        """Deep user with 60+ days inactive → building (2 levels down)."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-demote-60",
            created_at=now - timedelta(days=120),
            last_active_at=now - timedelta(days=65),
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-demote-60", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-demote-60")
        assert result["level"] == "building"
        assert result["daily_cap"] == 3

    async def test_no_demotion_when_recently_active(self, db_session, patch_async_session):
        """Deep user active 5 days ago → stays deep."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-active",
            created_at=now - timedelta(days=120),
            last_active_at=now - timedelta(days=5),
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-active", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-active")
        assert result["level"] == "deep"

    async def test_demotion_floors_at_new(self, db_session, patch_async_session):
        """Building user with 60+ days inactive → floors at new (not negative)."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-floor",
            created_at=now - timedelta(days=25),
            last_active_at=now - timedelta(days=65),
        )
        db_session.add(user)
        for i in range(25):
            db_session.add(make_chat_message("trust-floor", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-floor")
        assert result["level"] == "new"

    async def test_no_demotion_without_last_active(self, db_session, patch_async_session):
        """Deep user with no last_active_at → no demotion (no crash)."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        user = make_user(
            id="trust-no-active",
            created_at=now - timedelta(days=120),
            last_active_at=None,
        )
        db_session.add(user)
        for i in range(200):
            db_session.add(make_chat_message("trust-no-active", role="user", content=f"msg {i}"))
        await db_session.commit()

        result = await compute_trust_level("trust-no-active")
        assert result["level"] == "deep"
