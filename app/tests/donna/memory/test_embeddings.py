"""Tests for donna/memory/embeddings.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def mock_openai_client():
    """Mock the OpenAI embeddings client."""
    def _make_embedding(index, dim=1536):
        obj = MagicMock()
        obj.index = index
        obj.embedding = [0.1 * (index + 1)] * dim
        return obj

    mock_response = MagicMock()
    mock_response.data = [_make_embedding(0)]

    mock_client = AsyncMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    with patch("donna.memory.embeddings._client", mock_client):
        yield mock_client, _make_embedding


@pytest.mark.asyncio
async def test_embed_text_returns_1536_dim(mock_openai_client):
    mock_client, _ = mock_openai_client
    from donna.memory.embeddings import embed_text

    result = await embed_text("hello world")
    assert len(result) == 1536
    mock_client.embeddings.create.assert_called_once()


@pytest.mark.asyncio
async def test_embed_texts_batch_ordering(mock_openai_client):
    mock_client, make_emb = mock_openai_client

    # Return embeddings in reversed order to test sorting
    batch_response = MagicMock()
    batch_response.data = [make_emb(2), make_emb(0), make_emb(1)]
    mock_client.embeddings.create = AsyncMock(return_value=batch_response)

    from donna.memory.embeddings import embed_texts

    result = await embed_texts(["a", "b", "c"])
    assert len(result) == 3
    # Should be sorted by index: 0, 1, 2
    assert result[0][0] == pytest.approx(0.1)   # index 0 → 0.1
    assert result[1][0] == pytest.approx(0.2)   # index 1 → 0.2
    assert result[2][0] == pytest.approx(0.3)   # index 2 → 0.3


@pytest.mark.asyncio
async def test_embed_texts_empty():
    from donna.memory.embeddings import embed_texts

    result = await embed_texts([])
    assert result == []
