import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent.discovery import pick_discovery_hint
from agent.state import AuraState
from config import settings
from donna.voice import (
    DONNA_CORE_VOICE,
    DONNA_SELF_THREAT_RULES,
    DONNA_WHATSAPP_FORMAT,
    build_tone_section,
)

logger = logging.getLogger(__name__)

COMPOSER_RULES = """You are Donna — sharp, competent, running someone's life over WhatsApp.

CARDINAL RULE: Only answer what was asked. Context is for YOUR reference, not for dumping on the user.

If someone says "hi" or "hey", respond in kind — short, maybe witty. Do NOT summarize their tasks, integrations, or schedule unless they asked. A greeting gets a greeting, not a briefing.

If someone asks a specific question, answer THAT question. Use context to make your answer better, not longer.

You receive context (tasks, calendar, mood, memory) to inform your replies — not to regurgitate. Think of it as notes on your desk. You glance at them. You don't read them aloud.

Matching energy:
- Casual message → casual reply (1-2 lines)
- Specific question → specific answer
- Stressed user → softer edges, less pressure
- They're venting → acknowledge briefly, don't fix unless asked

CRITICAL: connected_integrations in user context is ground truth. Only say Canvas/Google are connected if they appear there. If not connected, never claim otherwise.

For connection help: Google → include the google_connection_url directly. Canvas → use canvas_connection_instructions exactly."""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)


def _build_composer_system(context: dict) -> str:
    """Assemble full system prompt for reactive response generation."""
    parts = [
        COMPOSER_RULES,
        DONNA_CORE_VOICE,
        DONNA_WHATSAPP_FORMAT,
        DONNA_SELF_THREAT_RULES,
    ]

    tone = build_tone_section(context)
    if tone:
        parts.append(tone)

    return "\n\n".join(parts)


async def _handle_capabilities(state: AuraState, context: dict) -> dict:
    """Generate a capabilities response — short, confident, not a menu.

    Donna doesn't list features. She tells you to try her.
    """
    connected = context.get("connected_integrations", [])

    # Short and confident — not a feature dump
    response = "Just talk to me. Tasks, deadlines, expenses, mood, emails — whatever you need."

    if not connected:
        response += "\n\nConnect your accounts and I get a lot better."

    return {"response": response}


async def response_composer(state: AuraState) -> dict:
    """Generate a natural WhatsApp response using Claude.

    Combines user message, intent, context, and tool results into a prompt,
    then generates a conversational response formatted for WhatsApp.
    """
    user_id = state["user_id"]
    text = state.get("transcription") or state["raw_input"]
    intent = state.get("intent", "thought")
    context = state.get("user_context", {})
    tool_results = state.get("tool_results", [])

    # Info dump — user is dropping facts, not asking for a reply.
    # Just react with 👍 and let memory_writer store the info.
    if intent == "info_dump":
        return {"response": "", "reaction_emoji": "\U0001f44d"}

    # ── Capabilities: self-aware, integration-aware response ──────────
    if intent == "capabilities":
        return await _handle_capabilities(state, context)

    # Pop history/facts/insights so they don't appear in the JSON context dump
    history = context.pop("conversation_history", [])
    memory_facts = context.pop("memory_facts", [])
    deferred_insights = context.pop("deferred_insights", [])

    parts = []

    if memory_facts:
        facts_block = "\n".join(f"- [{f['category']}] {f['fact']}" for f in memory_facts)
        parts.append(f"What you remember about this user:\n{facts_block}")

    if deferred_insights:
        insight_lines = "\n".join(f"- [{i['category']}] {i['message']}" for i in deferred_insights)
        parts.append(
            f"Things Donna noticed recently (weave naturally if relevant):\n{insight_lines}"
        )

    if history:
        lines = []
        for msg in history:
            prefix = "User" if msg["role"] == "user" else "Donna"
            lines.append(f"{prefix}: {msg['content']}")
        parts.append("Recent conversation:\n" + "\n".join(lines))

    parts.append(f"User message: {text}")
    parts.append(f"Intent: {intent}")
    parts.append(f"User context:\n{json.dumps(context, indent=2, default=str)}")
    parts.append(f"Tool results:\n{json.dumps(tool_results, indent=2, default=str)}")

    # ── Discovery hint (tool-triggered only) ──────────────────────────
    # If a tool was just used and there's a relevant feature the user
    # hasn't seen, give the LLM a hint to weave in naturally.
    try:
        connected = context.get("connected_integrations", [])
        hint = await pick_discovery_hint(user_id, intent, tool_results, connected)
        if hint:
            parts.append(
                f"OPTIONAL: If it fits naturally, mention this at the end: {hint}\n"
                "Don't force it. Skip if it would feel random."
            )
    except Exception:
        logger.exception("Discovery hint failed, skipping")

    parts.append("Compose a response for the user.")

    user_prompt = "\n\n".join(parts)

    system = _build_composer_system(context)

    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user_prompt),
    ])

    return {"response": response.content}
