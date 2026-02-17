"""Naturalize hardcoded responses into conversational language."""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.state import AuraState
from config import settings
from donna.voice import DONNA_CORE_VOICE

logger = logging.getLogger(__name__)

NATURALIZER_PROMPT = f"""You are Donna. Rewrite this system message the way Donna would actually text it.

{DONNA_CORE_VOICE}

Same information, same intent. Don't add facts. Don't sound like a bot. Don't sound like a template. Say it once, say it well.

- Concise. WhatsApp, not an essay.
- *Bold* where it helps.

Raw message to naturalize:
"""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)


async def naturalizer(state: AuraState) -> dict:
    """Rewrite hardcoded responses into natural, conversational language."""
    response = state.get("response")
    if not response or not response.strip():
        return {}

    user_input = (state.get("transcription") or state.get("raw_input", "")).strip()
    context = state.get("user_context", {})

    prompt = f"""{NATURALIZER_PROMPT}

"{response}"
"""
    if user_input:
        prompt += f"\n(User just said: {user_input})"

    # Pass tone preference if available
    user = context.get("user", {}) if isinstance(context, dict) else {}
    tone_pref = user.get("tone_preference")
    if tone_pref:
        prompt += f"\n(User prefers {tone_pref} tone)"

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
