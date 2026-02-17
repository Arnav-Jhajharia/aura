"""ReAct-style planner node for the Aura agent graph.

Instead of the classifier predicting all tools upfront, the planner
iteratively decides what information it needs, calls one tool at a time,
observes the result, and decides whether to call another tool or hand off
to the composer.  Maximum 3 iterations to bound latency and cost.
"""

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AuraState
from config import settings

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3

PLANNER_PROMPT = """You are Donna's reasoning engine. You have the user's message, \
their intent, extracted entities, and conversation history.

Decide your next action:
1. {{"action": "call_tool", "tool": "tool_name", "args": {{...}}}} — if you need information
2. {{"action": "done"}} — if you have enough to compose a response

What you know so far:
{accumulated_tool_results}

Available tools:
- get_calendar_events: Fetch calendar events for a date range. args: {{"date": "YYYY-MM-DD"}}
- create_calendar_event: Create a new calendar event. args: {{"title": "...", "start": "...", "end": "..."}}
- find_free_slots: Find free time slots. args: {{"date": "YYYY-MM-DD"}}
- canvas_assignments: Get upcoming Canvas assignments. No args needed.
- canvas_grades: Get recent Canvas grades. No args needed.
- get_emails: Check recent emails. args: {{"query": "..."}} (optional)
- send_email: Send an email. args: {{"to": "...", "subject": "...", "body": "..."}}
- create_task: Create a task/reminder. args: {{"title": "...", "due_date": "..."}}
- get_tasks: List pending tasks. No args needed.
- complete_task: Complete a task. args: {{"task_id": "..."}}
- save_journal_entry: Save a journal entry. args: {{"content": "...", "entry_type": "..."}}
- log_mood: Log a mood score. args: {{"score": 1-10, "note": "..."}}
- get_mood_history: Get recent mood scores. args: {{"days": 7}}
- log_expense: Log an expense. args: {{"amount": 0.00, "category": "...", "description": "..."}}
- get_expense_summary: Get spending summary. args: {{"days": 7}}
- search_memory: Search user's stored memories. args: {{"query": "..."}}
- recall_context: Load a specific context slice. args: {{"aspect": "tasks|moods|deadlines|expenses|deferred_insights"}}

Rules:
- Maximum {max_iterations} tool calls per turn. You've used {iterations_used} so far.
- Don't call tools you don't need. A greeting needs zero tools.
- If the user is venting, you probably need zero tools — just go to done.
- search_memory is your most powerful tool — use it when the user references \
something from the past that isn't in the immediate context.
- recall_context gives you structured DB data (tasks, moods, expenses, deadlines). \
Use it when the user asks about their tasks, mood trends, spending, or upcoming deadlines.
- For questions about calendar/email/assignments, use the specific tool directly.

Return ONLY valid JSON. No markdown, no explanation."""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)

# Intents that typically don't need any tool calls
_NO_TOOL_INTENTS = {"thought", "vent", "info_dump", "reflection", "capabilities"}


async def planner(state: AuraState) -> dict:
    """ReAct planner: decide what tool to call next, or hand off to composer."""
    text = state.get("transcription") or state["raw_input"]
    intent = state.get("intent", "thought")
    tool_results = state.get("tool_results", [])
    history = state.get("user_context", {}).get("conversation_history", [])[-6:]
    iterations = state.get("_planner_iterations", 0)

    # Fast-path: thoughts, vents, info_dumps, reflections skip tools entirely
    # (unless we already have tool results from a previous iteration, meaning
    # the planner previously decided it needed tools)
    if intent in _NO_TOOL_INTENTS and not tool_results:
        return {"_planner_action": "done", "_planner_iterations": iterations}

    # Safety: max iterations reached
    if iterations >= MAX_ITERATIONS:
        logger.info("Planner hit max iterations (%d), handing off to composer", MAX_ITERATIONS)
        return {"_planner_action": "done", "_planner_iterations": iterations}

    # Build context for the LLM
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

    user_block = (
        f"User message: {text}\n"
        f"Intent: {intent}\n"
        f"Entities: {json.dumps(entities, default=str)}"
    )
    if history_text:
        user_block = f"Conversation history:\n{history_text}\n\n{user_block}"

    prompt = PLANNER_PROMPT.format(
        accumulated_tool_results=results_summary,
        max_iterations=MAX_ITERATIONS,
        iterations_used=iterations,
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

    if action == "call_tool":
        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args", {})
        logger.info("Planner iteration %d: calling %s(%s)", iterations + 1, tool_name, tool_args)
        return {
            "_planner_action": "call_tool",
            "_next_tool": tool_name,
            "_next_tool_args": tool_args,
            "_planner_iterations": iterations + 1,
        }

    return {"_planner_action": "done", "_planner_iterations": iterations}
