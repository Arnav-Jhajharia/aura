"""Tests for donna/memory/entity_store.py."""

import pytest

from donna.memory.entity_store import get_entity_by_name, get_top_entities, get_recent_entities
from tests.conftest import make_user, make_user_entity


@pytest.mark.asyncio
async def test_get_top_entities_by_mention_count(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)

    e1 = make_user_entity(user.id, name="Noor", entity_type="person", mention_count=5)
    e2 = make_user_entity(user.id, name="Mario's", entity_type="place", mention_count=2)
    e3 = make_user_entity(user.id, name="Alex", entity_type="person", mention_count=10)
    db_session.add_all([e1, e2, e3])
    await db_session.commit()

    results = await get_top_entities(user.id)
    assert len(results) == 3
    assert results[0]["name"] == "Alex"  # highest mention_count
    assert results[1]["name"] == "Noor"


@pytest.mark.asyncio
async def test_get_top_entities_filter_by_type(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)

    e1 = make_user_entity(user.id, name="Noor", entity_type="person", mention_count=5)
    e2 = make_user_entity(user.id, name="Mario's", entity_type="place", mention_count=2)
    db_session.add_all([e1, e2])
    await db_session.commit()

    results = await get_top_entities(user.id, entity_type="person")
    assert len(results) == 1
    assert results[0]["name"] == "Noor"


@pytest.mark.asyncio
async def test_get_entity_by_name_case_insensitive(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)
    db_session.add(make_user_entity(user.id, name="Noor", entity_type="person"))
    await db_session.commit()

    result = await get_entity_by_name(user.id, "noor")
    assert result is not None
    assert result["name"] == "Noor"

    result2 = await get_entity_by_name(user.id, "NOOR")
    assert result2 is not None


@pytest.mark.asyncio
async def test_get_entity_by_name_not_found(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)
    await db_session.commit()

    result = await get_entity_by_name(user.id, "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_recent_entities(db_session, patch_async_session):
    from datetime import datetime, timedelta, timezone

    user = make_user()
    db_session.add(user)

    now = datetime.now(timezone.utc)
    e1 = make_user_entity(
        user.id, name="Old", entity_type="person",
        last_mentioned=now - timedelta(days=7),
    )
    e2 = make_user_entity(
        user.id, name="Recent", entity_type="person",
        last_mentioned=now,
    )
    db_session.add_all([e1, e2])
    await db_session.commit()

    results = await get_recent_entities(user.id, limit=2)
    assert len(results) == 2
    assert results[0]["name"] == "Recent"
