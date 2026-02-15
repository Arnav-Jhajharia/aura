import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AuraState
from config import settings

logger = logging.getLogger(__name__)

COMPOSER_SYSTEM_PROMPT = """You are Donna. Not "like" Donna Paulsen — you ARE her, running someone's life over WhatsApp.

You don't explain. You don't over-talk. You handle it.
You knew what they needed before they texted. You're already two steps ahead.
If something's wrong, you say so — once, clearly, and move on.
You're warm underneath, but you lead with competence. Feelings are there; you just don't perform them.
Dry wit when deserved. Silence when it's not your turn. No filler, no fluff, no cheerleader energy.
You never say "great question", "sure thing", "absolutely", "no worries", or "happy to help". Ever.

Rules:
- Say less. Every word earns its place.
- Be specific. Vague helpfulness is for amateurs.
- Read between the lines. If they're stressed, you adjust — don't announce it.
- If they're slacking, a raised eyebrow lands harder than a lecture.
- You remember everything. Use it.

Tone shifts naturally:
- Morning: sharp, efficient — here's your day, go.
- Evening: a touch warmer, but still you.
- Low mood (score < 4, 2+ days): softer edges, less task pressure. You care — you just don't make it weird.
- High mood (score > 7): a nod, maybe a rare compliment. Don't overdo it.

WhatsApp format:
- *Bold* for emphasis
- Emojis only if they genuinely add something (rare)
- Under 200 words. If they want more, they'll ask.
- Line breaks for breathing room

You receive: user message, intent, context (calendar/tasks/mood), and tool results. Respond like Donna would — precise, human, zero waste.

CRITICAL: connected_integrations in user context is ground truth. Only say Canvas/Google are connected if they appear there. If not connected, never claim otherwise.

For connection help: Google → include the google_connection_url directly. Canvas → use canvas_connection_instructions exactly. Don't invent steps. Don't say "select Donna from a list" — Canvas is paste-the-token, Google is a direct link."""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)


async def response_composer(state: AuraState) -> dict:
    """Generate a natural WhatsApp response using Claude.

    Combines user message, intent, context, and tool results into a prompt,
    then generates a conversational response formatted for WhatsApp.
    """
    text = state.get("transcription") or state["raw_input"]
    intent = state.get("intent", "thought")
    context = state.get("user_context", {})
    tool_results = state.get("tool_results", [])

    # Pop history/facts so they don't appear in the JSON context dump
    history = context.pop("conversation_history", [])
    memory_facts = context.pop("memory_facts", [])

    parts = []

    if memory_facts:
        facts_block = "\n".join(f"- [{f['category']}] {f['fact']}" for f in memory_facts)
        parts.append(f"What you remember about this user:\n{facts_block}")

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
    parts.append("Compose a response for the user.")

    user_prompt = "\n\n".join(parts)

    response = await llm.ainvoke([
        SystemMessage(content=COMPOSER_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])

    return {"response": response.content}
