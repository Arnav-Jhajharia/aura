import json
import logging
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

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
[{"fact": "...", "category": "preference|pattern|context|relationship"}]

If there are no notable facts to remember, return an empty array: []

Only extract genuinely useful, long-term facts — not transient information."""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)


async def memory_writer(state: AuraState) -> dict:
    """Extract memory facts from the conversation and send the response to WhatsApp.

    1. Uses Claude to extract memorable facts from the conversation.
    2. Stores extracted facts in the memory_facts table.
    3. Sends the composed response to the user via WhatsApp.
    """
    user_id = state["user_id"]
    phone = state["phone"]
    text = state.get("transcription") or state["raw_input"]
    response = state.get("response", "")

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

    # Extract memory facts
    memory_updates = []
    if text:
        try:
            extraction = await llm.ainvoke([
                SystemMessage(content=MEMORY_EXTRACTION_PROMPT),
                HumanMessage(content=f"User said: {text}\nAssistant replied: {response}"),
            ])
            facts = json.loads(extraction.content)

            async with async_session() as session:
                for fact_data in facts:
                    # Generate embedding (graceful degradation)
                    vector = None
                    try:
                        vector = await embed_text(fact_data["fact"])
                    except Exception:
                        logger.debug("Embedding failed for memory fact, storing without vector")

                    fact = MemoryFact(
                        id=generate_uuid(),
                        user_id=user_id,
                        fact=fact_data["fact"],
                        category=fact_data.get("category", "context"),
                        embedding=vector,
                    )
                    session.add(fact)
                    memory_updates.append(fact_data)
                await session.commit()

        except Exception:
            logger.exception("Failed to extract/store memory facts")

    # Extract structured entities from the user's message
    if text:
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
