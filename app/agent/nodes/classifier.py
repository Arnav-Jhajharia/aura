import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AuraState
from config import settings

logger = logging.getLogger(__name__)

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

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)


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

    return {
        "intent": parsed.get("intent", "thought"),
        "entities": parsed.get("entities", {}),
        "tools_needed": [],  # planner handles tool selection now
    }
