"""Semantic memory recall — finds relevant memories for the current context."""

import json
import logging
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select, or_

from config import settings
from db.models import MemoryFact
from db.session import async_session

logger = logging.getLogger(__name__)

QUERY_GEN_PROMPT = """Given the current signals and recent conversation below, suggest 3-5 short
search keywords or phrases to look up in the user's memory. These should help find past mentions
of people, places, events, or preferences that might be relevant right now.

Return ONLY a JSON array of strings. No markdown, no explanation.

Example: ["restaurant", "noor birthday", "gym", "SE assignment"]"""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0)


async def recall_relevant_memories(user_id: str, context: dict, limit: int = 10) -> list[dict]:
    """Search user's memory for facts relevant to current signals and context.

    Uses LLM to generate search queries from context, then does keyword
    search against MemoryFact via ILIKE.

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

    # Search MemoryFact for each query via ILIKE
    seen_ids: set[str] = set()
    results: list[dict] = []

    async with async_session() as session:
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
            facts = fact_result.scalars().all()

            for f in facts:
                if f.id not in seen_ids:
                    seen_ids.add(f.id)
                    results.append({
                        "fact": f.fact,
                        "category": f.category,
                        "confidence": f.confidence,
                        "created_at": f.created_at.isoformat() if f.created_at else None,
                    })

        # Update last_referenced on recalled facts
        if seen_ids:
            now = datetime.now(timezone.utc)
            for fact_id in seen_ids:
                await session.execute(
                    select(MemoryFact).where(MemoryFact.id == fact_id)
                )
            # Bulk update via individual loads
            for fact_id in seen_ids:
                fact_obj = await session.get(MemoryFact, fact_id)
                if fact_obj:
                    fact_obj.last_referenced = now
            await session.commit()

    logger.info(
        "Recalled %d memories for user %s from %d queries",
        len(results), user_id, len(queries),
    )

    return results[:limit]
