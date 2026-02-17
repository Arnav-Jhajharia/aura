"""Tests for donna/memory/recall.py — tests ILIKE fallback path (SQLite = no pgvector)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_memory_fact, make_user


@pytest.mark.asyncio
async def test_ilike_fallback_finds_matching_facts(db_session, patch_async_session):
    """ILIKE fallback should find facts containing query keywords."""
    import donna.memory.recall as recall_mod
    recall_mod._pgvector_available = None  # reset cache

    user = make_user()
    db_session.add(user)
    db_session.add(make_memory_fact(user.id, fact="loves pizza from Mario's"))
    db_session.add(make_memory_fact(user.id, fact="gym every morning at 7am"))
    db_session.add(make_memory_fact(user.id, fact="birthday is Feb 20"))
    await db_session.commit()

    # Mock LLM to return search queries
    mock_response = MagicMock()
    mock_response.content = '["pizza", "gym"]'
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    with patch.object(recall_mod, "llm", mock_llm):
        results = await recall_mod.recall_relevant_memories(
            user.id, {"signals": [], "recent_conversation": []},
        )

    assert len(results) == 2
    facts_text = {r["fact"] for r in results}
    assert "loves pizza from Mario's" in facts_text
    assert "gym every morning at 7am" in facts_text


@pytest.mark.asyncio
async def test_empty_query_returns_empty(db_session, patch_async_session):
    """If LLM returns empty queries, should return empty."""
    import donna.memory.recall as recall_mod
    recall_mod._pgvector_available = None

    mock_response = MagicMock()
    mock_response.content = "[]"
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    with patch.object(recall_mod, "llm", mock_llm):
        results = await recall_mod.recall_relevant_memories(
            "nonexistent-user", {"signals": [], "recent_conversation": []},
        )

    assert results == []


@pytest.mark.asyncio
async def test_recall_updates_last_referenced(db_session, patch_async_session):
    """Recalled facts should have last_referenced updated."""
    import donna.memory.recall as recall_mod
    recall_mod._pgvector_available = None

    user = make_user()
    fact = make_memory_fact(user.id, fact="CS2103T assignment due Friday")
    db_session.add(user)
    db_session.add(fact)
    await db_session.commit()

    assert fact.last_referenced is None

    mock_response = MagicMock()
    mock_response.content = '["CS2103T"]'
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    with patch.object(recall_mod, "llm", mock_llm):
        results = await recall_mod.recall_relevant_memories(
            user.id, {"signals": [], "recent_conversation": []},
        )

    assert len(results) == 1

    # Re-fetch from DB to check last_referenced was set
    await db_session.refresh(fact)
    assert fact.last_referenced is not None
