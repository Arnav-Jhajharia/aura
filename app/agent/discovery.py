"""Progressive discovery hints — reveal features at natural moments.

Hints only fire after tool usage (not on greetings or random messages).
They're passed to the composer as context for the LLM to weave in
naturally, not bolted on as a separate paragraph.

Tracked per-user via MemoryFact so we never repeat.
"""

import logging
from datetime import datetime

from sqlalchemy import select

from db.models import MemoryFact
from db.session import async_session

logger = logging.getLogger(__name__)

HINT_CATEGORY = "discovery:shown"

# ── Hint definitions ──────────────────────────────────────────────────────────
# Only trigger on tool results — never on intents alone (too noisy).
# Each hint fires once, ever, for that user.
DISCOVERY_HINTS = [
    {
        "hint_id": "expense_after_task",
        "trigger": "tool:create_task",
        "text": "I also track expenses if you tell me what you spent.",
    },
    {
        "hint_id": "journal_after_mood",
        "trigger": "tool:log_mood",
        "text": "You can also journal with me — text or voice notes.",
    },
    {
        "hint_id": "email_send_after_read",
        "trigger": "tool:get_emails",
        "text": "I can draft and send emails for you too.",
    },
    {
        "hint_id": "free_slots_after_calendar",
        "trigger": "tool:get_calendar_events",
        "text": "Ask me to find free time if you need a slot.",
    },
    {
        "hint_id": "expense_summary_after_log",
        "trigger": "tool:log_expense",
        "text": "Ask how much you spent this week anytime.",
    },
    {
        "hint_id": "memory_after_search",
        "trigger": "tool:search_memory",
        "text": "The more you tell me, the better I remember.",
    },
]


async def get_shown_hints(user_id: str) -> set[str]:
    """Load which hints have already been shown to this user."""
    async with async_session() as session:
        result = await session.execute(
            select(MemoryFact.fact)
            .where(
                MemoryFact.user_id == user_id,
                MemoryFact.category == HINT_CATEGORY,
            )
        )
        return {row[0] for row in result.all()}


async def mark_hint_shown(user_id: str, hint_id: str) -> None:
    """Record that a hint has been shown."""
    async with async_session() as session:
        fact = MemoryFact(
            user_id=user_id,
            category=HINT_CATEGORY,
            fact=hint_id,
            created_at=datetime.utcnow(),
        )
        session.add(fact)
        await session.commit()


async def pick_discovery_hint(
    user_id: str,
    intent: str,
    tool_results: list[dict],
    connected_integrations: list[str],
) -> str | None:
    """Pick a discovery hint if a tool was just used, or None.

    Only fires on tool-result triggers. Never on bare intents or greetings.
    Returns hint text for the LLM to weave in, not for mechanical appending.
    """
    # No tools used → no hint. Period.
    if not tool_results:
        return None

    shown = await get_shown_hints(user_id)

    # Build trigger set from tools that actually ran
    active_triggers: set[str] = set()
    for tr in tool_results:
        tool_name = tr.get("tool", "")
        if tool_name:
            active_triggers.add(f"tool:{tool_name}")

    if not active_triggers:
        return None

    for hint in DISCOVERY_HINTS:
        if hint["hint_id"] in shown:
            continue
        if hint["trigger"] in active_triggers:
            await mark_hint_shown(user_id, hint["hint_id"])
            return hint["text"]

    return None
