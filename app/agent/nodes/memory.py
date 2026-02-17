import json
import logging
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import func, select

from agent.conversation_summary import maybe_update_summary
from agent.state import AuraState
from config import settings
from db.models import ChatMessage, MemoryFact, User, generate_uuid
from db.session import async_session
from donna.brain.feedback import (
    apply_meta_feedback,
    check_and_update_feedback,
    detect_meta_feedback,
)
from donna.memory.embeddings import embed_text
from donna.memory.entities import extract_entities
from tools.whatsapp import react_to_message, send_whatsapp_message

logger = logging.getLogger(__name__)

MEMORY_EXTRACTION_PROMPT = """Extract key facts or preferences from this conversation that would be
useful to remember about the user for future interactions. Return a JSON array of objects:
[{"fact": "...", "category": "preference|pattern|context|relationship", "salience": 0.0-1.0}]

If there are no notable facts to remember, return an empty array: []

Only extract genuinely useful, long-term facts — not transient information.
Rate salience: 1.0 = critical life fact, 0.5 = moderately useful, 0.0 = trivial.
Skip anything below 0.5 salience."""

# Use gpt-4o-mini for memory extraction — good enough and cheaper
llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key)

# Intents that never produce useful memory facts
_SKIP_MEMORY_INTENTS = {"thought", "capabilities"}

# Similarity threshold for dedup (ILIKE prefix match)
_DEDUP_PREFIX_LENGTH = 50


async def _dedup_and_store_facts(
    user_id: str, facts: list[dict]
) -> list[dict]:
    """Store memory facts with deduplication.

    Before inserting, check if a very similar fact already exists (ILIKE match
    on the first N chars). If so, update the existing fact's last_referenced
    timestamp instead of creating a duplicate.
    """
    stored = []
    async with async_session() as session:
        for fact_data in facts:
            fact_text = fact_data["fact"]
            salience = fact_data.get("salience", 0.8)

            # Skip low-salience facts
            if salience < 0.5:
                continue

            # Dedup check: look for existing fact with similar prefix
            prefix = fact_text[:_DEDUP_PREFIX_LENGTH].lower()
            existing_result = await session.execute(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    func.lower(func.substr(MemoryFact.fact, 1, _DEDUP_PREFIX_LENGTH)) == prefix,
                ).limit(1)
            )
            existing = existing_result.scalar_one_or_none()

            if existing:
                # Update existing fact's timestamp
                existing.last_referenced = datetime.now(timezone.utc).replace(tzinfo=None)
                logger.debug("Dedup: updated existing fact '%s...'", prefix[:30])
            else:
                # Generate embedding (graceful degradation)
                vector = None
                try:
                    vector = await embed_text(fact_text)
                except Exception:
                    logger.debug("Embedding failed for memory fact, storing without vector")

                fact = MemoryFact(
                    id=generate_uuid(),
                    user_id=user_id,
                    fact=fact_text,
                    category=fact_data.get("category", "context"),
                    confidence=salience,
                    embedding=vector,
                )
                session.add(fact)
                stored.append(fact_data)

        await session.commit()
    return stored


async def memory_writer(state: AuraState) -> dict:
    """Extract memory facts from the conversation and send the response to WhatsApp.

    1. Persists the conversation turn to chat history.
    2. Extracts memorable facts (skipping trivial intents, with dedup).
    3. Extracts structured entities.
    4. Updates proactive feedback and meta-feedback.
    5. Persists pending flow state for multi-turn interactions.
    6. Triggers conversation summary update if due.
    7. Sends the composed response to the user via WhatsApp.
    """
    user_id = state["user_id"]
    phone = state["phone"]
    text = state.get("transcription") or state["raw_input"]
    response = state.get("response", "")
    intent = state.get("intent", "thought")

    # Persist conversation turn to chat history + update activity stats
    if text or response:
        try:
            async with async_session() as session:
                if text:
                    session.add(ChatMessage(
                        id=generate_uuid(), user_id=user_id, role="user", content=text,
                    ))
                if response:
                    session.add(ChatMessage(
                        id=generate_uuid(), user_id=user_id, role="assistant", content=response,
                    ))

                # Update user activity stats
                if text:
                    result = await session.execute(select(User).where(User.id == user_id))
                    user = result.scalar_one_or_none()
                    if user:
                        user.last_active_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        user.total_messages = (getattr(user, "total_messages", None) or 0) + 1

                await session.commit()
        except Exception:
            logger.exception("Failed to persist chat messages")

    # Extract memory facts (skip trivial intents)
    memory_updates: list[dict] = []
    if text and intent not in _SKIP_MEMORY_INTENTS:
        try:
            extraction = await llm.ainvoke([
                SystemMessage(content=MEMORY_EXTRACTION_PROMPT),
                HumanMessage(content=f"User said: {text}\nAssistant replied: {response}"),
            ])
            facts = json.loads(extraction.content)
            memory_updates = await _dedup_and_store_facts(user_id, facts)
        except Exception:
            logger.exception("Failed to extract/store memory facts")

    # Extract structured entities (skip trivial)
    if text and intent not in _SKIP_MEMORY_INTENTS:
        try:
            await extract_entities(user_id, text)
        except Exception:
            logger.exception("Entity extraction failed for user %s", user_id)

    # Update proactive feedback (mark recent proactive messages as engaged)
    try:
        await check_and_update_feedback(user_id, reply_text=text)
    except Exception:
        logger.exception("Feedback update failed for user %s", user_id)

    # Detect and apply meta-feedback about Donna's proactive behavior
    if text:
        try:
            meta_signals = detect_meta_feedback(text)
            if meta_signals:
                await apply_meta_feedback(user_id, meta_signals)
                logger.info("Applied %d meta-feedback signal(s) for user %s", len(meta_signals), user_id)
        except Exception:
            logger.exception("Meta-feedback detection failed for user %s", user_id)

    # Persist pending flow state for multi-turn interactions
    pending_flow = state.get("_pending_flow")
    try:
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.pending_flow_json = pending_flow  # None clears it
                await session.commit()
    except Exception:
        logger.exception("Failed to persist pending flow for user %s", user_id)

    # Trigger conversation summary update (async, non-blocking for the response)
    try:
        await maybe_update_summary(user_id)
    except Exception:
        logger.exception("Conversation summary update failed for user %s", user_id)

    # Send response to WhatsApp
    reaction_emoji = state.get("reaction_emoji")
    wa_message_id = state.get("wa_message_id")

    if reaction_emoji and wa_message_id:
        try:
            await react_to_message(to=phone, message_id=wa_message_id, emoji=reaction_emoji)
        except Exception:
            logger.debug("Failed to send reaction")

    if response:
        await send_whatsapp_message(to=phone, text=response)

    return {"memory_updates": memory_updates}
