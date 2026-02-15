"""Pattern detection — identifies recurring behavioral patterns from user history."""

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from config import settings
from db.models import ChatMessage, MemoryFact, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Analyze this user's chat history and stored memory facts to identify recurring behavioral patterns.

Look for:
- Temporal patterns (always messages at certain times, gym in the morning, late-night ideas)
- Emotional patterns (stress before deadlines, upbeat on weekends)
- Behavioral patterns (forgets water, procrastinates assignments, asks about same people)
- Social patterns (mentions certain friends regularly, group study habits)

For each pattern found, provide:
- "pattern": a short slug (e.g. "gym_morning", "late_night_ideas", "deadline_stress")
- "description": 1-2 sentence description of the pattern
- "confidence": 0.0-1.0 (how confident are you this is a real pattern, not noise?)

Only return patterns you're fairly confident about (>0.5). If there isn't enough data, return [].

Return ONLY a JSON array. No markdown, no explanation."""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0.3)

MIN_MESSAGES_FOR_PATTERNS = 5


async def detect_patterns(user_id: str) -> list[dict]:
    """Analyze user's history to detect behavioral patterns.

    Returns list of pattern dicts. Also stores new patterns as MemoryFacts
    with category="pattern".
    """
    async with async_session() as session:
        # Pull recent chat messages
        msg_result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(50)
        )
        messages = msg_result.scalars().all()

        if len(messages) < MIN_MESSAGES_FOR_PATTERNS:
            return []

        # Pull existing memory facts
        facts_result = await session.execute(
            select(MemoryFact)
            .where(MemoryFact.user_id == user_id)
            .order_by(MemoryFact.created_at.desc())
            .limit(30)
        )
        facts = facts_result.scalars().all()

    # Build input for LLM
    messages_text = "\n".join(
        f"[{m.created_at.isoformat() if m.created_at else '?'}] {m.role}: {m.content}"
        for m in reversed(messages)
    )
    facts_text = "\n".join(f"- [{f.category}] {f.fact}" for f in facts) if facts else "(no stored facts)"

    user_prompt = f"Chat history:\n{messages_text}\n\nStored memory facts:\n{facts_text}"

    try:
        response = await llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
    except Exception:
        logger.exception("LLM call failed in pattern detection")
        return []

    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        patterns = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse pattern JSON: %s", raw[:200])
        return []

    if not isinstance(patterns, list):
        return []

    valid: list[dict] = []
    for p in patterns:
        if not isinstance(p, dict) or "pattern" not in p:
            continue
        valid.append({
            "pattern": p["pattern"],
            "description": p.get("description", ""),
            "confidence": min(max(float(p.get("confidence", 0.5)), 0.0), 1.0),
        })

    # Store as MemoryFacts (skip duplicates by checking existing pattern facts)
    if valid:
        try:
            async with async_session() as session:
                existing_result = await session.execute(
                    select(MemoryFact.fact)
                    .where(
                        MemoryFact.user_id == user_id,
                        MemoryFact.category == "pattern",
                    )
                )
                existing_facts = {row[0] for row in existing_result.all()}

                for p in valid:
                    fact_text = f"{p['pattern']}: {p['description']}"
                    if fact_text not in existing_facts:
                        session.add(MemoryFact(
                            id=generate_uuid(),
                            user_id=user_id,
                            fact=fact_text,
                            category="pattern",
                            confidence=p["confidence"],
                        ))
                await session.commit()
            logger.info("Detected %d patterns for user %s", len(valid), user_id)
        except Exception:
            logger.exception("Failed to store patterns for user %s", user_id)

    return valid
