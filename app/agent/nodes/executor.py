import asyncio
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

# Errors that are transient and worth retrying once
_TRANSIENT_ERRORS = ("timeout", "rate limit", "429", "503", "502", "connection")


def _is_transient(error_str: str) -> bool:
    lower = error_str.lower()
    return any(t in lower for t in _TRANSIENT_ERRORS)


async def _execute_one(
    tool_name: str, user_id: str, entities: dict, tool_args: dict
) -> dict:
    """Execute a single tool with retry on transient errors."""
    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn is None:
        logger.warning("Unknown tool requested: %s", tool_name)
        return {"tool": tool_name, "error": "unknown tool"}

    for attempt in range(2):  # max 1 retry
        try:
            result = await tool_fn(user_id=user_id, entities=entities, **tool_args)
            return {"tool": tool_name, "result": result}
        except Exception as e:
            error_str = str(e)
            if attempt == 0 and _is_transient(error_str):
                logger.info("Transient error on %s, retrying once: %s", tool_name, error_str)
                await asyncio.sleep(1)
                continue
            logger.exception("Tool %s failed", tool_name)
            return {"tool": tool_name, "error": error_str}

    # Should not reach here, but just in case
    return {"tool": tool_name, "error": "max retries exceeded"}


async def tool_executor(state: AuraState) -> dict:
    """Execute tools — single, parallel, or batch from tools_needed.

    In planner mode:
    - _next_tool: execute one tool
    - _next_tools: execute multiple tools in parallel
    Legacy mode (tools_needed list): iterate through all requested tools.
    """
    user_id = state["user_id"]
    entities = state.get("entities", {})
    results = list(state.get("tool_results", []))

    # ── Parallel tool execution (call_tools) ─────────────────────────────
    next_tools = state.get("_next_tools")
    if next_tools:
        tasks = []
        for t in next_tools:
            name = t.get("tool", "")
            args = t.get("args", {})
            tasks.append(_execute_one(name, user_id, entities, args))

        parallel_results = await asyncio.gather(*tasks)
        results.extend(parallel_results)

        return {
            "tool_results": results,
            "_next_tool": None,
            "_next_tool_args": None,
            "_next_tools": None,
        }

    # ── Planner-driven single-tool execution ─────────────────────────────
    next_tool = state.get("_next_tool")
    if next_tool:
        tool_args = state.get("_next_tool_args") or {}
        result = await _execute_one(next_tool, user_id, entities, tool_args)
        results.append(result)

        return {
            "tool_results": results,
            "_next_tool": None,
            "_next_tool_args": None,
        }

    # ── Legacy batch execution (tools_needed from classifier) ────────────
    tools_needed = state.get("tools_needed", [])
    for tool_name in tools_needed:
        result = await _execute_one(tool_name, user_id, entities, {})
        results.append(result)

    return {"tool_results": results}
