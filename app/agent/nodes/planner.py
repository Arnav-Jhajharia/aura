"""ReAct-style planner node for the Aura agent graph.

Instead of the classifier predicting all tools upfront, the planner
iteratively decides what information it needs, calls one (or multiple
parallel) tools at a time, observes the result, and decides whether to
call another tool or hand off to the composer.  Maximum 5 iterations.
"""

import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AuraState
from config import settings

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5

PLANNER_PROMPT = """You are Donna's reasoning engine. You have the user's message, \
their intent, extracted entities, and conversation history.

Current date/time: {current_datetime}

Decide your next action:
1. {{"action": "call_tool", "tool": "tool_name", "args": {{...}}}} — call a single tool
2. {{"action": "call_tools", "tools": [{{"tool": "...", "args": {{...}}}}, ...]}} — call multiple independent tools in parallel
3. {{"action": "done"}} — if you have enough to compose a response

What you know so far:
{accumulated_tool_results}

User's connected integrations: {connected_integrations}

Available tools:
**Canvas (requires canvas):**
- canvas_courses: Get user's enrolled courses. No args needed.
- canvas_assignments: Get upcoming assignments. args: {{"days_ahead": 7}} (optional)
- canvas_grades: Get recent grades. No args needed.
- canvas_announcements: Get recent announcements across all courses. No args needed.
- canvas_course_info: Get detailed info about a specific course. args: {{"course_name": "..."}} or {{"course_id": "..."}}
- canvas_submission_status: Check submission status for upcoming assignments. No args needed.

**Calendar (requires google or microsoft):**
- get_calendar_events: Fetch events for a date range. args: {{"date": "YYYY-MM-DD", "days": 1}}
- create_calendar_event: Create a new event. args: {{"title": "...", "start": "ISO", "end": "ISO", "description": "..."}}
- find_free_slots: Find free time slots. args: {{"date": "YYYY-MM-DD"}}
- update_calendar_event: Update an event. args: {{"event_id": "...", "title": "...", "start": "...", "end": "..."}}
- delete_calendar_event: Delete an event. args: {{"event_id": "..."}}

**Email (requires google or microsoft):**
- get_emails: Check recent emails. args: {{"filter": "unread|important|all", "count": 10}}
- get_email_detail: Get the full body of a specific email. args: {{"email_id": "..."}}
- reply_to_email: Reply to an email. args: {{"email_id": "...", "body": "..."}}
- send_email: Send a new email. args: {{"to": "...", "subject": "...", "body": "..."}}

**Tasks & Productivity:**
- create_task: Create a task/reminder. args: {{"title": "...", "due_date": "..."}}
- get_tasks: List pending tasks. No args needed.
- complete_task: Complete a task. args: {{"task_id": "..."}}
- sync_nusmods_to_calendar: Sync NUSMods timetable to calendar. args: {{"nusmods_url": "..."}} (requires google or microsoft)

**Journal & Mood:**
- save_journal_entry: Save a journal entry. args: {{"content": "...", "entry_type": "..."}}
- log_mood: Log a mood score. args: {{"score": 1-10, "note": "..."}}
- get_mood_history: Get recent mood scores. args: {{"days": 7}}
- log_expense: Log an expense. args: {{"amount": 0.00, "category": "...", "description": "..."}}
- get_expense_summary: Get spending summary. args: {{"days": 7}}

**Memory & Context:**
- search_memory: Search user's stored memories. args: {{"query": "..."}}
- search_voice_notes: Search past voice note transcripts. args: {{"query": "..."}}
- get_voice_note_summary: Get full transcript of a voice note. args: {{"voice_note_id": "..."}}
- recall_context: Load a specific context slice. args: {{"aspect": "tasks|moods|deadlines|expenses|deferred_insights"}}

Rules:
- Maximum {max_iterations} tool calls per turn. You've used {iterations_used} so far.
- Don't call tools you don't need. A greeting needs zero tools.
- If the user is venting, you probably need zero tools — just go to done.
- Only call tools that require an integration if that integration is in the connected list above.
- When the user asks "what's due", "deadlines", "assignments" and canvas is connected, ALWAYS call canvas_assignments.
- When the user asks about their courses, modules, or whether they're taking a specific course, call canvas_courses.
- When the user asks "did I submit X?" or "what haven't I submitted?", call canvas_submission_status.
- When the user asks about announcements or news from their courses, call canvas_announcements.
- When the user asks about a specific course (syllabus, instructor, details), call canvas_course_info.
- When the user asks about schedule/calendar and google or microsoft is connected, call get_calendar_events.
- When the user wants to read a specific email (not just the subject), call get_email_detail first.
- When the user wants to reply to an email, call reply_to_email with the email_id and body.
- When the user pastes a NUSMods URL, call sync_nusmods_to_calendar.
- search_memory is your most powerful tool — use it when the user references \
something from the past that isn't in the immediate context.
- recall_context gives you structured DB data (tasks, moods, expenses, deadlines). \
Use it when the user asks about their tasks, mood trends, spending, or upcoming deadlines.
- When you need multiple INDEPENDENT pieces of information (e.g. assignments AND calendar), \
use call_tools to fetch them in parallel instead of calling them one at a time.
- If a tool returned an error about an expired or missing integration, do NOT retry it. \
Instead, go to done — the composer will suggest reconnecting.
- Use the current date/time to compute relative dates: "tomorrow", "this Friday", "next week".

Return ONLY valid JSON. No markdown, no explanation."""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)

# Intents that typically don't need any tool calls
_NO_TOOL_INTENTS = {"thought", "vent", "info_dump", "reflection", "capabilities"}

# ── Deterministic tool routing ───────────────────────────────────────────
# Keyword → (tool_name, required_integration_or_None, tool_args)
# Checked BEFORE the LLM planner. Guarantees the right tool fires on obvious requests.
_KEYWORD_ROUTES: list[tuple[list[str], str, str | None, dict]] = [
    # Canvas — courses
    (["my courses", "my modules", "am i taking", "am i enrolled", "what courses",
      "which courses", "course list", "enrolled in", "taking this sem",
      "what modules", "which modules"],
     "canvas_courses", "canvas", {}),
    # Canvas — assignments (expanded)
    (["assignment", "assignments", "what's due", "whats due", "due date", "due this",
      "deadline", "deadlines", "upcoming due", "homework", "hw",
      "what do i have due", "anything due", "submissions due"],
     "canvas_assignments", "canvas", {}),
    # Canvas — grades (expanded)
    (["grade", "grades", "marks", "score", "scores", "gpa", "results",
      "how did i do", "my marks", "my results"],
     "canvas_grades", "canvas", {}),
    # Canvas — announcements (expanded)
    (["announcement", "announcements", "course news", "course updates", "prof said",
      "professor posted", "lecturer posted", "prof posted", "any news",
      "course announcement"],
     "canvas_announcements", "canvas", {}),
    # Canvas — submission status (expanded)
    (["did i submit", "have i submitted", "submission status", "haven't submitted",
      "not submitted", "missing submission", "what haven't i submitted",
      "unsubmitted"],
     "canvas_submission_status", "canvas", {}),
    # Calendar — view (expanded)
    (["calendar", "schedule", "events today", "events this", "what's on", "whats on",
      "busy today", "busy this", "what do i have today", "what do i have tomorrow",
      "what do i have this week", "any meetings", "my meetings", "my events",
      "what's happening", "whats happening", "lectures today", "tutorial today",
      "class today", "classes today", "classes tomorrow"],
     "get_calendar_events", None, {}),
    # Calendar — free slots (expanded)
    (["free today", "free this", "when am i free", "free slot", "free time",
      "available time", "find time", "am i free", "do i have time",
      "any free time", "open slots"],
     "find_free_slots", None, {}),
    # Email — list (expanded)
    (["email", "emails", "inbox", "mail", "unread", "check email",
      "any emails", "new emails", "my inbox", "check my email"],
     "get_emails", None, {}),
    # NUSMods (expanded)
    (["nusmods.com/timetable", "nusmods url", "sync timetable", "sync nusmods",
      "import timetable", "nusmods link"],
     "sync_nusmods_to_calendar", None, {}),
    # Tasks — view (expanded)
    (["my tasks", "pending tasks", "task list", "to do", "todo", "to-do",
      "what do i need to do", "my to-do", "show tasks"],
     "get_tasks", None, {}),
    # Mood (expanded)
    (["mood history", "mood trend", "how have i been", "mood log",
      "mood tracker", "my mood", "mood lately"],
     "get_mood_history", None, {"days": 7}),
    # Expenses (expanded)
    (["spending", "expenses", "how much have i spent", "expense summary",
      "my spending", "money spent", "budget", "spending summary",
      "how much did i spend"],
     "get_expense_summary", None, {"days": 7}),
    # Voice notes
    (["voice note", "voice notes", "what did i say", "my recordings",
      "voice memo", "voice memos"],
     "search_voice_notes", None, {}),
    # Memory — recall (expanded)
    (["remember when", "what did i tell you about", "what do you know about",
      "do you remember", "i mentioned", "i told you"],
     "search_memory", None, {}),
]


def _deterministic_route(text: str, connected: list[str]) -> tuple[str, dict] | None:
    """Check if user message matches a keyword route. Returns (tool, args) or None."""
    lower = text.lower()
    for keywords, tool, required_integration, args in _KEYWORD_ROUTES:
        if any(kw in lower for kw in keywords):
            # Skip if tool requires an integration the user doesn't have
            if required_integration and required_integration not in connected:
                continue
            # For calendar/email, need google or microsoft
            if tool in ("get_calendar_events", "get_emails", "find_free_slots",
                        "create_calendar_event", "send_email", "get_email_detail",
                        "reply_to_email", "delete_calendar_event",
                        "update_calendar_event", "sync_nusmods_to_calendar"):
                if "google" not in connected and "microsoft" not in connected:
                    continue
            # Dynamic args for search_memory
            actual_args = dict(args)
            if tool == "search_memory":
                actual_args["query"] = text
            return (tool, actual_args)
    return None


def _format_user_datetime(tz_name: str) -> str:
    """Format current date/time in the user's timezone."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    return now.strftime("%A, %B %d, %Y at %I:%M %p") + f" ({tz_name})"


async def planner(state: AuraState) -> dict:
    """ReAct planner: decide what tool to call next, or hand off to composer."""
    text = state.get("transcription") or state["raw_input"]
    intent = state.get("intent", "thought")
    tool_results = state.get("tool_results", [])
    history = state.get("user_context", {}).get("conversation_history", [])[-10:]
    iterations = state.get("_planner_iterations", 0)
    connected = state.get("user_context", {}).get("connected_integrations", [])
    pending_flow = state.get("_pending_flow")

    # Fast-path: thoughts, vents, info_dumps, reflections skip tools entirely
    # (unless we already have tool results from a previous iteration, meaning
    # the planner previously decided it needed tools)
    if intent in _NO_TOOL_INTENTS and not tool_results and not pending_flow:
        return {"_planner_action": "done", "_planner_iterations": iterations}

    # ── Deterministic routing (iteration 0 only) ─────────────────────────
    if iterations == 0 and not pending_flow:
        route = _deterministic_route(text, connected)
        if route:
            tool_name, tool_args = route
            logger.info("Deterministic route: %s for '%s'", tool_name, text[:50])
            return {
                "_planner_action": "call_tool",
                "_next_tool": tool_name,
                "_next_tool_args": tool_args,
                "_planner_iterations": iterations + 1,
            }

    # Safety: max iterations reached
    if iterations >= MAX_ITERATIONS:
        logger.info("Planner hit max iterations (%d), handing off to composer", MAX_ITERATIONS)
        return {"_planner_action": "done", "_planner_iterations": iterations}

    # ── Build context for the LLM ────────────────────────────────────────
    results_summary = (
        json.dumps(tool_results, indent=2, default=str) if tool_results else "None yet."
    )

    history_text = ""
    if history:
        lines = []
        for msg in history:
            prefix = "User" if msg["role"] == "user" else "Donna"
            lines.append(f"{prefix}: {msg['content']}")
        history_text = "\n".join(lines)

    entities = state.get("entities", {})
    profile = state.get("user_context", {}).get("user_profile", {})
    memory_facts = state.get("user_context", {}).get("memory_facts", [])
    user_entities = state.get("user_context", {}).get("user_entities", {})
    conversation_summary = state.get("user_context", {}).get("conversation_summary", "")

    # Format current datetime in user's timezone
    tz_name = state.get("user_context", {}).get("timezone", "UTC")
    current_dt = _format_user_datetime(tz_name)

    user_block_parts = []

    # Conversation summary (compressed older history)
    if conversation_summary:
        user_block_parts.append(f"Conversation summary (older context):\n{conversation_summary}")

    if history_text:
        user_block_parts.append(f"Recent conversation:\n{history_text}")

    # Memory facts (what Donna knows about this user)
    if memory_facts:
        facts_lines = "\n".join(
            f"- [{f.get('category', '?')}] {f['fact']}"
            for f in memory_facts[:10]
        )
        user_block_parts.append(f"What you remember about this user:\n{facts_lines}")

    # Known entities (people, places, etc.)
    if user_entities:
        entity_parts = []
        for etype in ("people", "places", "recent"):
            items = user_entities.get(etype, [])
            if items:
                names = ", ".join(e.get("name", "?") for e in items[:5])
                entity_parts.append(f"  {etype}: {names}")
        if entity_parts:
            user_block_parts.append("Known entities:\n" + "\n".join(entity_parts))

    # Pending flow (multi-turn context)
    if pending_flow:
        user_block_parts.append(
            f"PENDING FLOW: There is an ongoing multi-turn interaction.\n"
            f"Flow type: {pending_flow.get('type', 'unknown')}\n"
            f"Context: {json.dumps(pending_flow.get('context', {}), default=str)}\n"
            f"Awaiting: {pending_flow.get('awaiting', 'unknown')}\n"
            f"The user's current message is likely a response to this flow. "
            f"Interpret it accordingly."
        )

    user_block_parts.append(
        f"User message: {text}\n"
        f"Intent: {intent}\n"
        f"Entities: {json.dumps(entities, default=str)}"
    )
    if profile:
        user_block_parts.append(f"User profile: {json.dumps(profile, default=str)}")

    user_block = "\n\n".join(user_block_parts)

    prompt = PLANNER_PROMPT.format(
        accumulated_tool_results=results_summary,
        connected_integrations=", ".join(connected) if connected else "none",
        max_iterations=MAX_ITERATIONS,
        iterations_used=iterations,
        current_datetime=current_dt,
    )

    response = await llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=user_block),
    ])

    try:
        parsed = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning("Planner returned invalid JSON, falling through to composer")
        return {"_planner_action": "done", "_planner_iterations": iterations}

    action = parsed.get("action", "done")

    # Single tool call
    if action == "call_tool":
        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args", {})
        logger.info("Planner iteration %d: calling %s(%s)", iterations + 1, tool_name, tool_args)
        result: dict = {
            "_planner_action": "call_tool",
            "_next_tool": tool_name,
            "_next_tool_args": tool_args,
            "_planner_iterations": iterations + 1,
        }
        # Planner can set a pending flow for multi-turn interactions
        if "pending_flow" in parsed:
            result["_pending_flow"] = parsed["pending_flow"]
        return result

    # Parallel tool calls
    if action == "call_tools":
        tools_list = parsed.get("tools", [])
        if tools_list:
            logger.info(
                "Planner iteration %d: parallel calling %s",
                iterations + 1,
                [t.get("tool") for t in tools_list],
            )
            result = {
                "_planner_action": "call_tools",
                "_next_tools": tools_list,
                "_planner_iterations": iterations + len(tools_list),
            }
            if "pending_flow" in parsed:
                result["_pending_flow"] = parsed["pending_flow"]
            return result

    # Done
    result = {"_planner_action": "done", "_planner_iterations": iterations}
    if "pending_flow" in parsed:
        result["_pending_flow"] = parsed["pending_flow"]
    return result
