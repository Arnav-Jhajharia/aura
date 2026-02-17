import logging

from agent.state import AuraState
from tools.tasks import create_task, complete_task, get_tasks
from tools.journal import save_journal_entry, log_mood, get_mood_history
from tools.expenses import log_expense, get_expense_summary
from tools.canvas import (
    get_canvas_assignments, get_canvas_courses, get_canvas_grades,
    get_canvas_announcements, get_canvas_course_info,
    get_canvas_submission_status,
)
from tools.email import get_emails, send_email, get_email_detail, reply_to_email
from tools.calendar import (
    get_calendar_events, create_calendar_event, find_free_slots,
    delete_calendar_event, update_calendar_event,
)
from tools.voice import search_voice_notes, get_voice_note_summary
from tools.nusmods import sync_nusmods_to_calendar
from tools.memory_search import search_memory
from tools.recall_context import recall_context

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
    "canvas_courses": get_canvas_courses,
    "canvas_grades": get_canvas_grades,
    "canvas_announcements": get_canvas_announcements,
    "canvas_course_info": get_canvas_course_info,
    "canvas_submission_status": get_canvas_submission_status,
    "get_emails": get_emails,
    "send_email": send_email,
    "get_email_detail": get_email_detail,
    "reply_to_email": reply_to_email,
    "get_calendar_events": get_calendar_events,
    "create_calendar_event": create_calendar_event,
    "find_free_slots": find_free_slots,
    "delete_calendar_event": delete_calendar_event,
    "update_calendar_event": update_calendar_event,
    "search_voice_notes": search_voice_notes,
    "get_voice_note_summary": get_voice_note_summary,
    "sync_nusmods_to_calendar": sync_nusmods_to_calendar,
    "search_memory": search_memory,
    "recall_context": recall_context,
}


async def tool_executor(state: AuraState) -> dict:
    """Execute tools — either a single tool from the planner or a batch from tools_needed.

    In planner mode (_next_tool is set): execute one tool, append result to
    tool_results, and return.  The planner loop will decide what to do next.

    Legacy mode (tools_needed list): iterate through all requested tools.
    """
    user_id = state["user_id"]
    entities = state.get("entities", {})
    results = list(state.get("tool_results", []))

    # ── Planner-driven single-tool execution ──────────────────────────
    next_tool = state.get("_next_tool")
    if next_tool:
        tool_fn = TOOL_REGISTRY.get(next_tool)
        if tool_fn is None:
            logger.warning("Planner requested unknown tool: %s", next_tool)
            results.append({"tool": next_tool, "error": "unknown tool"})
        else:
            tool_args = state.get("_next_tool_args") or {}
            try:
                result = await tool_fn(user_id=user_id, entities=entities, **tool_args)
                results.append({"tool": next_tool, "result": result})
            except Exception as e:
                logger.exception("Tool %s failed", next_tool)
                results.append({"tool": next_tool, "error": str(e)})

        # Clear the single-tool directive so the planner can issue a new one
        return {
            "tool_results": results,
            "_next_tool": None,
            "_next_tool_args": None,
        }

    # ── Legacy batch execution (tools_needed from classifier) ─────────
    tools_needed = state.get("tools_needed", [])
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
