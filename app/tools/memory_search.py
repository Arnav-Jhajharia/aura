import logging
from datetime import datetime, timezone

from sqlalchemy import select, text

from db.models import MemoryFact
from db.session import async_session
from donna.memory.embeddings import embed_text

logger = logging.getLogger(__name__)

# Cache per process
_pgvector_available: bool | None = None


async def _has_pgvector(session) -> bool:
    global _pgvector_available
    if _pgvector_available is not None:
        return _pgvector_available
    try:
        await session.execute(text("SELECT 1::vector(1)"))
        _pgvector_available = True
    except Exception:
        _pgvector_available = False
    return _pgvector_available


async def search_memory(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Search over stored user facts and context.

    Uses pgvector cosine distance when available, falls back to ILIKE keyword search.
    """
    query = kwargs.get("query", "")

    async with async_session() as session:
        use_vectors = await _has_pgvector(session)
        facts: list[MemoryFact] = []

        if use_vectors and query:
            try:
                query_vector = await embed_text(query)
                result = await session.execute(
                    select(MemoryFact)
                    .where(
                        MemoryFact.user_id == user_id,
                        MemoryFact.embedding.isnot(None),
                    )
                    .order_by(MemoryFact.embedding.cosine_distance(query_vector))
                    .limit(10)
                )
                facts = list(result.scalars().all())
            except Exception:
                logger.debug("Vector search failed, falling back to ILIKE")
                facts = []

            # Supplement with ILIKE if vector results are sparse
            if len(facts) < 3 and query:
                seen_ids = {f.id for f in facts}
                ilike_result = await session.execute(
                    select(MemoryFact)
                    .where(
                        MemoryFact.user_id == user_id,
                        MemoryFact.fact.ilike(f"%{query}%"),
                    )
                    .order_by(MemoryFact.created_at.desc())
                    .limit(10)
                )
                for f in ilike_result.scalars().all():
                    if f.id not in seen_ids:
                        facts.append(f)

        if not facts:
            # Pure ILIKE fallback (SQLite / no pgvector / no query)
            result = await session.execute(
                select(MemoryFact)
                .where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.fact.ilike(f"%{query}%"),
                )
                .order_by(MemoryFact.created_at.desc())
                .limit(10)
            )
            facts = list(result.scalars().all())

        # Update last_referenced timestamp
        for fact in facts:
            fact.last_referenced = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()

    return [
        {
            "fact": f.fact,
            "category": f.category,
            "confidence": f.confidence,
            "date": f.created_at.isoformat(),
        }
        for f in facts
    ]


async def get_user_context(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Get comprehensive user context for personalization."""
    from tools.tasks import get_tasks
    from tools.journal import get_mood_history

    tasks = await get_tasks(user_id, status="pending")
    moods = await get_mood_history(user_id, days=7)

    # Recent memory facts
    async with async_session() as session:
        result = await session.execute(
            select(MemoryFact)
            .where(MemoryFact.user_id == user_id)
            .order_by(MemoryFact.created_at.desc())
            .limit(10)
        )
        recent_facts = result.scalars().all()

    return {
        "pending_tasks": len(tasks),
        "recent_mood_avg": (
            round(sum(m["score"] for m in moods) / len(moods), 1) if moods else None
        ),
        "recent_topics": [f.fact for f in recent_facts[:5]],
    }
