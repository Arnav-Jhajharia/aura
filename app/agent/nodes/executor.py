import logging

from agent.state import AuraState
from tools.tasks import create_task, complete_task, get_tasks
from tools.journal import save_journal_entry, log_mood, get_mood_history
from tools.expenses import log_expense, get_expense_summary
from tools.canvas import get_canvas_assignments, get_canvas_grades
from tools.email import get_emails, send_email
from tools.calendar import get_calendar_events, create_calendar_event, find_free_slots
from tools.memory_search import search_memory

logger = logging.getLogger(__name__)

# Registry mapping tool names to callables
TOOL_REGISTRY: dict[str, callable] = {
    "create_task": create_task,
    "complete_task": complete_task,
    "get_tasks": get_tasks,
    "save_journal_entry": save_journal_entry,
    "log_mood": log_mood,
    "get_mood_history": get_mood_history,
    "log_expense": log_expense,
    "get_expense_summary": get_expense_summary,
    "canvas_assignments": get_canvas_assignments,
    "canvas_grades": get_canvas_grades,
    "get_emails": get_emails,
    "send_email": send_email,
    "get_calendar_events": get_calendar_events,
    "create_calendar_event": create_calendar_event,
    "find_free_slots": find_free_slots,
    "search_memory": search_memory,
}


async def tool_executor(state: AuraState) -> dict:
    """Execute tools requested by the intent classifier.

    Iterates through tools_needed and calls each with user_id and entities.
    Results are collected into tool_results.
    """
    tools_needed = state.get("tools_needed", [])
    user_id = state["user_id"]
    entities = state.get("entities", {})
    results = []

    for tool_name in tools_needed:
        tool_fn = TOOL_REGISTRY.get(tool_name)
        if tool_fn is None:
            logger.warning("Unknown tool requested: %s", tool_name)
            results.append({"tool": tool_name, "error": "unknown tool"})
            continue

        try:
            result = await tool_fn(user_id=user_id, entities=entities)
            results.append({"tool": tool_name, "result": result})
        except Exception as e:
            logger.exception("Tool %s failed", tool_name)
            results.append({"tool": tool_name, "error": str(e)})

    return {"tool_results": results}
