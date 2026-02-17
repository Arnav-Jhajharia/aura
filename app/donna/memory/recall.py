"""Semantic memory recall — finds relevant memories for the current context."""

import json
import logging
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select, text

from config import settings
from db.models import MemoryFact
from db.session import async_session
from donna.memory.embeddings import embed_text

logger = logging.getLogger(__name__)

QUERY_GEN_PROMPT = """Given the current signals and recent conversation below, suggest 3-5 short
search keywords or phrases to look up in the user's memory. These should help find past mentions
of people, places, events, or preferences that might be relevant right now.

Return ONLY a JSON array of strings. No markdown, no explanation.

Example: ["restaurant", "noor birthday", "gym", "SE assignment"]"""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0)

# Cache the pgvector check per process
_pgvector_available: bool | None = None


async def _has_pgvector(session) -> bool:
    """Runtime check for pgvector availability. Cached after first call."""
    global _pgvector_available
    if _pgvector_available is not None:
        return _pgvector_available
    try:
        await session.execute(text("SELECT 1::vector(1)"))
        _pgvector_available = True
    except Exception:
        _pgvector_available = False
    return _pgvector_available


async def _vector_search(
    session, user_id: str, query_text: str, limit: int,
) -> list[MemoryFact]:
    """Search via pgvector cosine distance."""
    try:
        query_vector = await embed_text(query_text)
    except Exception:
        logger.debug("Embedding failed for recall query, falling back to ILIKE")
        return []

    result = await session.execute(
        select(MemoryFact)
        .where(
            MemoryFact.user_id == user_id,
            MemoryFact.embedding.isnot(None),
        )
        .order_by(MemoryFact.embedding.cosine_distance(query_vector))
        .limit(limit)
    )
    return list(result.scalars().all())


async def _ilike_search(
    session, user_id: str, queries: list[str], limit: int,
) -> list[MemoryFact]:
    """Fallback keyword search via ILIKE."""
    seen_ids: set[str] = set()
    results: list[MemoryFact] = []

    for query in queries[:5]:
        if not isinstance(query, str) or not query.strip():
            continue
        fact_result = await session.execute(
            select(MemoryFact)
            .where(
                MemoryFact.user_id == user_id,
                MemoryFact.fact.ilike(f"%{query.strip()}%"),
            )
            .order_by(MemoryFact.created_at.desc())
            .limit(5)
        )
        for f in fact_result.scalars().all():
            if f.id not in seen_ids:
                seen_ids.add(f.id)
                results.append(f)

    return results[:limit]


async def recall_relevant_memories(user_id: str, context: dict, limit: int = 10) -> list[dict]:
    """Search user's memory for facts relevant to current signals and context.

    Uses pgvector cosine distance when available, falls back to ILIKE keyword search.
    Returns list of relevant memory facts with their metadata.
    """
    # Build a summary of current context for the LLM
    signals_summary = json.dumps(context.get("signals", []), default=str)
    conversation_summary = json.dumps(context.get("recent_conversation", [])[-5:], default=str)

    context_text = (
        f"Current signals:\n{signals_summary}\n\n"
        f"Recent conversation:\n{conversation_summary}\n\n"
        f"Day: {context.get('day_of_week', '')}, Time: {context.get('current_time', '')}"
    )

    # Ask LLM for search queries
    try:
        response = await llm.ainvoke([
            SystemMessage(content=QUERY_GEN_PROMPT),
            HumanMessage(content=context_text),
        ])
    except Exception:
        logger.exception("LLM call failed in memory recall query generation")
        return []

    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        queries = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse recall queries: %s", raw[:200])
        return []

    if not isinstance(queries, list) or not queries:
        return []

    # Search with dual-path: pgvector when available, ILIKE fallback
    seen_ids: set[str] = set()
    results: list[dict] = []

    async with async_session() as session:
        use_vectors = await _has_pgvector(session)

        if use_vectors:
            # Combine queries into one search string for vector search
            combined_query = " ".join(str(q) for q in queries[:5] if isinstance(q, str))
            vector_facts = await _vector_search(session, user_id, combined_query, limit)

            for f in vector_facts:
                seen_ids.add(f.id)
                results.append({
                    "fact": f.fact,
                    "category": f.category,
                    "confidence": f.confidence,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                })

            # Supplement with ILIKE if vector results are sparse
            if len(results) < 3:
                ilike_facts = await _ilike_search(session, user_id, queries, limit)
                for f in ilike_facts:
                    if f.id not in seen_ids:
                        seen_ids.add(f.id)
                        results.append({
                            "fact": f.fact,
                            "category": f.category,
                            "confidence": f.confidence,
                            "created_at": f.created_at.isoformat() if f.created_at else None,
                        })
        else:
            # Pure ILIKE fallback (SQLite / no pgvector)
            ilike_facts = await _ilike_search(session, user_id, queries, limit)
            for f in ilike_facts:
                seen_ids.add(f.id)
                results.append({
                    "fact": f.fact,
                    "category": f.category,
                    "confidence": f.confidence,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                })

        # Update last_referenced on recalled facts
        if seen_ids:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for fact_id in seen_ids:
                fact_obj = await session.get(MemoryFact, fact_id)
                if fact_obj:
                    fact_obj.last_referenced = now
            await session.commit()

    logger.info(
        "Recalled %d memories for user %s from %d queries (vector=%s)",
        len(results), user_id, len(queries), use_vectors,
    )

    return results[:limit]
