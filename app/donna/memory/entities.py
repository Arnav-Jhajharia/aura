"""Entity extraction — pulls structured entities from user messages and stores as MemoryFacts."""

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config import settings
from db.models import MemoryFact, generate_uuid
from db.session import async_session

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

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0)


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

                    session.add(MemoryFact(
                        id=generate_uuid(),
                        user_id=user_id,
                        fact=f"{e['entity']}: {context_str}",
                        category=f"entity:{e['type']}",
                        confidence=0.7,
                    ))
                await session.commit()
            logger.info("Stored %d entities for user %s", len(valid), user_id)
        except Exception:
            logger.exception("Failed to store entities for user %s", user_id)

    return valid
