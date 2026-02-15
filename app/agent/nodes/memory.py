import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AuraState
from config import settings
from db.models import ChatMessage, MemoryFact, generate_uuid
from db.session import async_session
from tools.whatsapp import send_whatsapp_message

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

    # Persist conversation turn to chat history
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
                    fact = MemoryFact(
                        id=generate_uuid(),
                        user_id=user_id,
                        fact=fact_data["fact"],
                        category=fact_data.get("category", "context"),
                    )
                    session.add(fact)
                    memory_updates.append(fact_data)
                await session.commit()

        except Exception:
            logger.exception("Failed to extract/store memory facts")

    # Send response to WhatsApp
    if response:
        await send_whatsapp_message(to=phone, text=response)

    return {"memory_updates": memory_updates}
