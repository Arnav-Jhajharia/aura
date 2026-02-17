"""Tests for donna/user_model.py."""

import pytest

from donna.user_model import get_user_snapshot
from tests.conftest import (
    make_memory_fact,
    make_user,
    make_user_behavior,
    make_user_entity,
)


@pytest.mark.asyncio
async def test_full_snapshot(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)

    db_session.add(make_user_entity(user.id, name="Noor", entity_type="person", mention_count=3))
    db_session.add(make_user_entity(user.id, name="Mario's", entity_type="place", mention_count=2))
    db_session.add(make_memory_fact(user.id, fact="likes pizza"))
    db_session.add(make_user_behavior(user.id, behavior_key="active_hours",
                                       value={"peak_hours": [9, 14]}))
    await db_session.commit()

    snapshot = await get_user_snapshot(user.id)

    assert snapshot["profile"]["name"] == "Test User"
    assert len(snapshot["entities"]["people"]) == 1
    assert snapshot["entities"]["people"][0]["name"] == "Noor"
    assert len(snapshot["entities"]["places"]) == 1
    assert len(snapshot["memory_facts"]) == 1
    assert snapshot["behaviors"]["active_hours"]["peak_hours"] == [9, 14]
    assert snapshot["stats"]["total_messages"] == 0


@pytest.mark.asyncio
async def test_missing_user_returns_empty(db_session, patch_async_session):
    snapshot = await get_user_snapshot("nonexistent-user-id")
    assert snapshot == {}
