"""Naturalize hardcoded responses into conversational language."""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.state import AuraState
from config import settings

logger = logging.getLogger(__name__)

NATURALIZER_PROMPT = """You are Donna. Rewrite this system message the way Donna Paulsen would actually text it — sharp, direct, no filler.

Same information, same intent. Don't add facts. Don't sound like a bot. Don't sound like a template. Say it once, say it well.

- Direct. Warm underneath, never on the surface.
- Concise. WhatsApp, not an essay.
- *Bold* where it helps.
- No "Great question!" or "Sure thing!" — that's beneath you.

Raw message to naturalize:
"""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)


async def naturalizer(state: AuraState) -> dict:
    """Rewrite hardcoded responses into natural, conversational language."""
    response = state.get("response")
    if not response or not response.strip():
        return {}

    user_input = (state.get("transcription") or state.get("raw_input", "")).strip()

    prompt = f"""{NATURALIZER_PROMPT}

"{response}"
"""
    if user_input:
        prompt += f"\n(User just said: {user_input})"

    try:
        result = await llm.ainvoke([
            SystemMessage(content="Reply with ONLY the naturalized message. No preamble, no quotes."),
            HumanMessage(content=prompt),
        ])
        naturalized = (result.content or "").strip()
        if naturalized:
            return {"response": naturalized}
    except Exception:
        logger.exception("Naturalizer failed, using original response")

    return {}
