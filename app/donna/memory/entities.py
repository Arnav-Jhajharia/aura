"""Entity extraction — pulls structured entities from user messages and stores as MemoryFacts + UserEntities."""

import json
import logging
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from config import settings
from db.models import MemoryFact, UserEntity, generate_uuid
from db.session import async_session
from donna.memory.embeddings import embed_text

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Extract structured entities from this user message. Return a JSON array of objects.

For each entity found, provide:
- "entity": the name or label (e.g. "chimichanga", "noor", "CS2103T")
- "type": one of [person, place, task, idea, event, preference]
- "context": a short phrase explaining why it was mentioned or what the user said about it
- "temporal": any time-related info mentioned (e.g. "sunday 2pm", "next week", "birthday Feb 20"), or null if none

Rules:
- Only extract genuinely meaningful entities — skip filler words, greetings, and generic phrases.
- If the message is too short or vague (like "lol ok" or "thanks"), return an empty array: []
- Prefer specificity: "chimichanga near campus" is better than just "restaurant"
- People's names should always be extracted as type "person"
- Assignments, homework, projects → type "task"
- Restaurants, cafes, locations → type "place"
- Birthdays, meetings, deadlines → type "event"
- "I like X", "I hate Y", food preferences → type "preference"

Return ONLY a JSON array. No markdown, no explanation."""

llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key, temperature=0)


async def extract_entities(user_id: str, message: str) -> list[dict]:
    """Extract people, places, dates, tasks, ideas from a user message.

    Returns list of dicts with entity, type, context, temporal fields.
    Also stores each entity as a MemoryFact with category="entity:<type>".
    """
    if not message or len(message.strip()) < 3:
        return []

    try:
        response = await llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=message),
        ])
    except Exception:
        logger.exception("LLM call failed in entity extraction")
        return []

    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        entities = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse entity JSON: %s", raw[:200])
        return []

    if not isinstance(entities, list):
        return []

    # Validate and normalize
    valid: list[dict] = []
    for e in entities:
        if not isinstance(e, dict) or "entity" not in e or "type" not in e:
            continue
        valid.append({
            "entity": e["entity"],
            "type": e["type"],
            "context": e.get("context", ""),
            "temporal": e.get("temporal"),
        })

    # Store as MemoryFacts
    if valid:
        try:
            async with async_session() as session:
                for e in valid:
                    context_str = e["context"]
                    if e["temporal"]:
                        context_str += f" (temporal: {e['temporal']})"

                    fact_text = f"{e['entity']}: {context_str}"

                    # Generate embedding (graceful degradation — store without if it fails)
                    vector = None
                    try:
                        vector = await embed_text(fact_text)
                    except Exception:
                        logger.debug("Embedding failed for entity fact, storing without vector")

                    session.add(MemoryFact(
                        id=generate_uuid(),
                        user_id=user_id,
                        fact=fact_text,
                        category=f"entity:{e['type']}",
                        confidence=0.7,
                        embedding=vector,
                    ))
                await session.commit()
            logger.info("Stored %d entity facts for user %s", len(valid), user_id)
        except Exception:
            logger.exception("Failed to store entity facts for user %s", user_id)

    # Upsert into UserEntity (structured storage for queries)
    if valid:
        try:
            async with async_session() as session:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                for e in valid:
                    name_normalized = e["entity"].strip().lower()
                    result = await session.execute(
                        select(UserEntity).where(
                            UserEntity.user_id == user_id,
                            UserEntity.entity_type == e["type"],
                            UserEntity.name_normalized == name_normalized,
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.mention_count += 1
                        existing.last_mentioned = now
                        # Append context
                        meta = existing.metadata_ or {}
                        contexts = meta.get("contexts", [])
                        contexts.append(e["context"])
                        meta["contexts"] = contexts[-10:]  # keep last 10
                        existing.metadata_ = meta
                    else:
                        session.add(UserEntity(
                            id=generate_uuid(),
                            user_id=user_id,
                            entity_type=e["type"],
                            name=e["entity"],
                            name_normalized=name_normalized,
                            metadata_={"contexts": [e["context"]]},
                            mention_count=1,
                            first_mentioned=now,
                            last_mentioned=now,
                        ))
                await session.commit()
            logger.info("Upserted %d user entities for user %s", len(valid), user_id)
        except Exception:
            logger.exception("Failed to upsert user entities for user %s", user_id)

    return valid
