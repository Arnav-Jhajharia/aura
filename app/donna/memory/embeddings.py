"""Embedding utilities — wraps OpenAI text-embedding-3-small for vector storage."""

import logging

from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=settings.openai_api_key)

MODEL = "text-embedding-3-small"


async def embed_text(text: str) -> list[float]:
    """Embed a single text string. Returns a 1536-dim vector."""
    response = await _client.embeddings.create(input=[text], model=MODEL)
    return response.data[0].embedding


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts in one API call. Returns vectors in input order."""
    if not texts:
        return []
    response = await _client.embeddings.create(input=texts, model=MODEL)
    # API returns embeddings sorted by index
    sorted_data = sorted(response.data, key=lambda d: d.index)
    return [d.embedding for d in sorted_data]
