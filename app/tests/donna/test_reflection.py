"""Tests for donna/reflection.py."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from db.models import UserBehavior
from donna.reflection import run_reflection
from tests.conftest import make_chat_message, make_user


@pytest.mark.asyncio
async def test_run_reflection_stores_behaviors(db_session, patch_async_session):
    """Reflection should store UserBehavior rows for user with data."""
    user = make_user()
    db_session.add(user)

    now = datetime.now(timezone.utc)
    for msg in ["hello", "how are you", "what time is lunch"]:
        db_session.add(make_chat_message(user.id, role="user", content=msg, created_at=now))
    await db_session.commit()

    await run_reflection(user.id)

    # Should have stored at least message_length_pref and active_hours
    result = await db_session.execute(
        select(UserBehavior).where(UserBehavior.user_id == user.id)
    )
    behaviors = result.scalars().all()
    keys = {b.behavior_key for b in behaviors}
    assert "message_length_pref" in keys
    assert "active_hours" in keys


@pytest.mark.asyncio
async def test_run_reflection_skips_no_data(db_session, patch_async_session):
    """Reflection should skip behaviors when user has no data."""
    user = make_user()
    db_session.add(user)
    await db_session.commit()

    await run_reflection(user.id)

    result = await db_session.execute(
        select(UserBehavior).where(UserBehavior.user_id == user.id)
    )
    behaviors = result.scalars().all()
    assert len(behaviors) == 0
