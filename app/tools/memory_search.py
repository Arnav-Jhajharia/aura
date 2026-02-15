import logging
from datetime import datetime

from sqlalchemy import select

from db.models import MemoryFact
from db.session import async_session

logger = logging.getLogger(__name__)


async def search_memory(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Search over stored user facts and context.

    TODO: Use pgvector embedding similarity search for semantic matching.
    Currently falls back to keyword search.
    """
    query = kwargs.get("query", "")

    async with async_session() as session:
        result = await session.execute(
            select(MemoryFact)
            .where(
                MemoryFact.user_id == user_id,
                MemoryFact.fact.ilike(f"%{query}%"),
            )
            .order_by(MemoryFact.created_at.desc())
            .limit(10)
        )
        facts = result.scalars().all()

        # Update last_referenced timestamp
        for fact in facts:
            fact.last_referenced = datetime.utcnow()
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
    """Get comprehensive user context for personalization.

    Aggregates recent mood, pending tasks, upcoming deadlines, and memory facts.
    """
    # This is largely handled by the context_loader node,
    # but this tool allows Claude to explicitly request a context refresh.
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
