import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AuraState
from config import settings

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """You are classifying a WhatsApp message from the user. Return JSON only:
{
  "intent": "task" | "question" | "thought" | "vent" | "command" | "reflection",
  "entities": {
    "dates": [],
    "people": [],
    "amounts": [],
    "topics": []
  },
  "tools_needed": ["tool_name_1", "tool_name_2"]
}

Intent definitions:
- task: user wants to create, complete, or check a task/reminder
- question: user is asking for information (from Canvas, email, calendar, or general)
- thought: user is sharing an idea, brain dump, or observation to be stored
- vent: user is expressing frustration or emotion (respond empathetically, log mood)
- command: user is giving a direct instruction (send email, create event, log expense)
- reflection: user is responding to a journal/reflection prompt

Available tools: canvas_assignments, canvas_grades, get_emails, send_email, reply_to_email,
get_calendar_events, create_calendar_event, find_free_slots, create_task, get_tasks,
complete_task, save_journal_entry, log_mood, get_mood_history, search_voice_notes,
log_expense, get_expense_summary, search_memory"""

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
    """Classify user intent and extract entities using Claude."""
    text = state.get("transcription") or state["raw_input"]

    if not text:
        return {
            "intent": "thought",
            "entities": {"dates": [], "people": [], "amounts": [], "topics": []},
            "tools_needed": [],
        }

    response = await llm.ainvoke([
        SystemMessage(content=CLASSIFICATION_PROMPT),
        HumanMessage(content=text),
    ])

    try:
        parsed = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning("Failed to parse classification response, defaulting to 'thought'")
        parsed = {
            "intent": "thought",
            "entities": {"dates": [], "people": [], "amounts": [], "topics": []},
            "tools_needed": [],
        }

    return {
        "intent": parsed.get("intent", "thought"),
        "entities": parsed.get("entities", {}),
        "tools_needed": parsed.get("tools_needed", []),
    }
