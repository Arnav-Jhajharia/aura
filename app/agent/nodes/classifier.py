import json
import logging
import re

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AuraState
from config import settings

logger = logging.getLogger(__name__)

# ── Deterministic question detection ────────────────────────────────────────
# If the LLM misclassifies an obvious question as info_dump/thought, override.
_QUESTION_WORD_RE = re.compile(
    r"^(what|when|where|who|why|how|which|is|are|do|does|did|can|could|will|would|should|have|has|any)\b",
    re.IGNORECASE,
)
_QUESTION_PHRASES = [
    "what's", "whats", "how's", "hows", "where's", "wheres", "who's", "whos",
    "when's", "whens", "do i", "am i", "is there", "are there", "tell me",
    "show me", "give me", "check my", "what about", "anything",
]
# Intents that should NOT be overridden even if message looks like a question
_NO_OVERRIDE_INTENTS = {"command", "vent", "reflection", "capabilities"}


def _looks_like_question(text: str) -> bool:
    """Heuristic: does this message look like a question?"""
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    lower = stripped.lower()
    if _QUESTION_WORD_RE.match(lower):
        return True
    return any(lower.startswith(p) for p in _QUESTION_PHRASES)

CLASSIFICATION_PROMPT = """You are classifying a WhatsApp message from the user.

Recent conversation for context:
{history}

Current message to classify:
{message}

Return JSON only:
{{
  "intent": "task" | "question" | "thought" | "info_dump" | "vent" | "command" | "reflection",
  "entities": {{
    "dates": [],
    "people": [],
    "amounts": [],
    "topics": []
  }}
}}

Use the conversation history to resolve references:
- "what about tomorrow?" after a calendar discussion → intent: question, topics: ["calendar"]
- "and assignments?" after discussing schedule → intent: question, topics: ["assignments"]
- "the 2pm one" → resolve to the specific event/task from history
- "thanks" after getting help → intent: thought (not question)

Intent definitions:
- task: user wants to create, complete, or check a task/reminder
- question: user is asking for information (from Canvas, email, calendar, or general)
- capabilities: user is asking what Donna can do, what features are available, or how to use something. Examples: "what can you do?", "how do I log expenses?", "what are you?", "help", "what else can you help with?"
- thought: user is sharing a casual message, greeting, or general chat (e.g. "hi", "thanks", "lol")
- info_dump: user is dropping facts/info for Donna to store — NOT asking for a response. Examples: "my exam is march 5th", "got 85 on midterm", "new TA is John", forwarded messages, pasting schedules/links/notes. The user just wants acknowledgment, not a reply.
- vent: user is expressing frustration or emotion (respond empathetically, log mood)
- command: user is giving a direct instruction (send email, create event, log expense)
- reflection: user is responding to a journal/reflection prompt

KEY DISTINCTION: "thought" means the user is chatting and expects a reply. "info_dump" means they're giving you information to remember — they just want a thumbs up, not a conversation."""

llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key)


def classify_type(state: AuraState) -> dict:
    """Route by message type: voice → transcriber, everything else → intent classifier."""
    return {"message_type": state["message_type"]}


def route_by_type(state: AuraState) -> str:
    """Conditional edge: route voice messages to transcriber, rest to classifier."""
    if state["message_type"] == "audio":
        return "voice"
    return "text"


async def intent_classifier(state: AuraState) -> dict:
    """Classify user intent and extract entities using the LLM.

    Now history-aware: uses the last 3 conversation turns to resolve
    references like "what about tomorrow?" or "and the other one?".
    Tool selection is no longer done here — the planner handles it.
    """
    text = state.get("transcription") or state["raw_input"]

    if not text:
        return {
            "intent": "thought",
            "entities": {"dates": [], "people": [], "amounts": [], "topics": []},
            "tools_needed": [],
        }

    # Pull conversation history loaded by ingress
    history = state.get("user_context", {}).get("conversation_history", [])[-6:]
    if history:
        lines = []
        for msg in history:
            prefix = "User" if msg["role"] == "user" else "Donna"
            lines.append(f"{prefix}: {msg['content']}")
        history_text = "\n".join(lines)
    else:
        history_text = "(no recent conversation)"

    prompt = CLASSIFICATION_PROMPT.format(history=history_text, message=text)

    response = await llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=text),
    ])

    try:
        parsed = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning("Failed to parse classification response, defaulting to 'thought'")
        parsed = {
            "intent": "thought",
            "entities": {"dates": [], "people": [], "amounts": [], "topics": []},
        }

    intent = parsed.get("intent", "thought")

    # ── Deterministic guard: prevent obvious questions from being buried ──
    if intent in ("info_dump", "thought") and intent not in _NO_OVERRIDE_INTENTS:
        if _looks_like_question(text):
            logger.info(
                "Override: '%s' classified as %s but looks like a question", text[:60], intent
            )
            intent = "question"

    return {
        "intent": intent,
        "entities": parsed.get("entities", {}),
        "tools_needed": [],  # planner handles tool selection now
    }
