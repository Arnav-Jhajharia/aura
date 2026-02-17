"""Result formatter — convert raw tool JSON into concise, human-readable text for the composer."""

import json
import logging

logger = logging.getLogger(__name__)

# Maximum tokens (approximate chars) for formatted tool results
MAX_RESULT_CHARS = 3000


def format_tool_results(tool_results: list[dict], user_message: str = "") -> str:
    """Format tool results into readable text for the composer.

    Instead of dumping raw JSON, this produces a concise summary that the
    composer can directly weave into a response.
    """
    if not tool_results:
        return "No tool results."

    parts = []
    for entry in tool_results:
        tool = entry.get("tool", "unknown")
        error = entry.get("error")
        result = entry.get("result")

        if error:
            parts.append(f"[{tool}] ERROR: {error}")
            continue

        if result is None:
            parts.append(f"[{tool}] No data returned.")
            continue

        formatted = _format_single(tool, result)
        parts.append(f"[{tool}]\n{formatted}")

    combined = "\n\n".join(parts)

    # Truncate if too long
    if len(combined) > MAX_RESULT_CHARS:
        combined = combined[:MAX_RESULT_CHARS] + "\n... (results truncated)"

    return combined


def _format_single(tool: str, result) -> str:
    """Format a single tool result based on tool type."""

    # Canvas assignments
    if tool == "canvas_assignments" and isinstance(result, list):
        if not result:
            return "No upcoming assignments found."
        lines = []
        for a in result[:10]:  # cap at 10
            name = a.get("name", "Untitled")
            course = a.get("course_name", "")
            due = a.get("due_at", "no due date")
            submitted = a.get("has_submitted_submissions", False)
            status = "submitted" if submitted else "not submitted"
            line = f"- {name}"
            if course:
                line += f" ({course})"
            line += f" — due {due}, {status}"
            lines.append(line)
        return "\n".join(lines)

    # Canvas courses
    if tool == "canvas_courses" and isinstance(result, list):
        if not result:
            return "No courses found."
        return "\n".join(f"- {c.get('name', 'Unknown')}" for c in result[:15])

    # Calendar events
    if tool == "get_calendar_events" and isinstance(result, list):
        if not result:
            return "No events found for this period."
        lines = []
        for e in result[:10]:
            title = e.get("title") or e.get("summary", "Untitled")
            start = e.get("start", "")
            end = e.get("end", "")
            line = f"- {title}: {start}"
            if end:
                line += f" → {end}"
            lines.append(line)
        return "\n".join(lines)

    # Free slots
    if tool == "find_free_slots" and isinstance(result, list):
        if not result:
            return "No free slots found."
        lines = []
        for s in result[:8]:
            start = s.get("start", "")
            end = s.get("end", "")
            lines.append(f"- {start} → {end}")
        return "\n".join(lines)

    # Emails
    if tool == "get_emails" and isinstance(result, list):
        if not result:
            return "No emails found."
        lines = []
        for e in result[:8]:
            sender = e.get("from", e.get("sender", "Unknown"))
            subject = e.get("subject", "No subject")
            date = e.get("date", "")
            lines.append(f"- From {sender}: \"{subject}\" ({date})")
        return "\n".join(lines)

    # Tasks
    if tool == "get_tasks" and isinstance(result, list):
        if not result:
            return "No pending tasks."
        lines = []
        for t in result[:10]:
            title = t.get("title", "Untitled")
            due = t.get("due_date", "no due date")
            lines.append(f"- {title} (due: {due})")
        return "\n".join(lines)

    # Grades
    if tool == "canvas_grades" and isinstance(result, list):
        if not result:
            return "No grades found."
        lines = []
        for g in result[:10]:
            course = g.get("course_name", "Unknown")
            grade = g.get("current_grade") or g.get("current_score", "N/A")
            lines.append(f"- {course}: {grade}")
        return "\n".join(lines)

    # Memory search
    if tool == "search_memory" and isinstance(result, list):
        if not result:
            return "No matching memories found."
        lines = [f"- {m.get('fact', str(m))}" for m in result[:8]]
        return "\n".join(lines)

    # Expense summary
    if tool == "get_expense_summary" and isinstance(result, dict):
        total = result.get("total", 0)
        by_cat = result.get("by_category", {})
        lines = [f"Total spent: ${total:.2f}"]
        for cat, amt in by_cat.items():
            lines.append(f"- {cat}: ${amt:.2f}")
        return "\n".join(lines)

    # Default: compact JSON
    try:
        text = json.dumps(result, indent=1, default=str)
        if len(text) > 1500:
            text = text[:1500] + "\n... (truncated)"
        return text
    except Exception:
        return str(result)[:1500]
