"""Context builder — assembles the full picture of a user's life for the LLM."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ChatMessage, Expense, MemoryFact, MoodLog, Task, User
from db.session import async_session
from donna.brain.rules import count_proactive_today
from donna.memory.recall import recall_relevant_memories
from donna.signals.base import Signal

logger = logging.getLogger(__name__)


async def build_context(user_id: str, signals: list[Signal]) -> dict:
    """Build a complete context window for the brain's LLM call.

    Returns a dict with everything Donna needs to decide what to say:
    - user profile
    - current signals
    - recent conversation
    - memory facts
    - pending tasks
    - recent mood
    - today's spending
    - current time info
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    context: dict = {
        "user_id": user_id,
        "current_time": now.isoformat(),
        "day_of_week": now.strftime("%A"),
    }

    # Signals (the reason we're considering messaging)
    context["signals"] = [
        {"type": s.type.value, "data": s.data, "urgency_hint": s.urgency_hint}
        for s in signals
    ]

    async with async_session() as session:
        # ── User profile ─────────────────────────────────────────────
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return context

        context["user"] = {
            "name": user.name or "",
            "timezone": user.timezone or "UTC",
            "wake_time": user.wake_time or "08:00",
            "sleep_time": user.sleep_time or "23:00",
            "reminder_frequency": user.reminder_frequency or "normal",
            "tone_preference": user.tone_preference or "casual",
        }

        # ── Recent conversation (last 10 messages) ───────────────────
        history_result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(10)
        )
        history = history_result.scalars().all()
        context["recent_conversation"] = [
            {
                "role": m.role,
                "content": m.content,
                "time": m.created_at.isoformat(),
            }
            for m in reversed(history)
        ]

        # ── Last assistant message time (for cooldown checks) ────────
        last_donna_result = await session.execute(
            select(ChatMessage.created_at)
            .where(ChatMessage.user_id == user_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        last_donna = last_donna_result.scalar_one_or_none()
        if last_donna:
            context["minutes_since_last_message"] = round(
                (now - last_donna).total_seconds() / 60, 1
            )
        else:
            context["minutes_since_last_message"] = None

        # ── Memory facts ─────────────────────────────────────────────
        facts_result = await session.execute(
            select(MemoryFact)
            .where(MemoryFact.user_id == user_id)
            .order_by(MemoryFact.created_at.desc())
            .limit(20)
        )
        facts = facts_result.scalars().all()
        context["memory_facts"] = [
            {"fact": f.fact, "category": f.category}
            for f in facts
        ]

        # ── Pending tasks ────────────────────────────────────────────
        tasks_result = await session.execute(
            select(Task)
            .where(Task.user_id == user_id, Task.status == "pending")
            .order_by(Task.due_date.asc().nullslast())
            .limit(15)
        )
        tasks = tasks_result.scalars().all()
        context["pending_tasks"] = [
            {
                "title": t.title,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "priority": t.priority,
                "source": t.source,
            }
            for t in tasks
        ]

        # ── Recent mood ──────────────────────────────────────────────
        seven_days_ago = now - timedelta(days=7)
        mood_result = await session.execute(
            select(MoodLog)
            .where(MoodLog.user_id == user_id, MoodLog.created_at >= seven_days_ago)
            .order_by(MoodLog.created_at.desc())
        )
        moods = mood_result.scalars().all()
        context["recent_moods"] = [
            {"score": m.score, "note": m.note, "date": m.created_at.isoformat()}
            for m in moods
        ]

        # ── Today's spending ─────────────────────────────────────────
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        expense_result = await session.execute(
            select(Expense)
            .where(Expense.user_id == user_id, Expense.created_at >= today_start)
        )
        expenses = expense_result.scalars().all()
        context["today_spending"] = round(sum(e.amount for e in expenses), 2)

    # ── Daily proactive message count ─────────────────────────────
    try:
        context["proactive_sent_today"] = await count_proactive_today(user_id)
    except Exception:
        logger.exception("Failed to count proactive messages for user %s", user_id)
        context["proactive_sent_today"] = 0

    # ── Recalled memories (semantic search) ─────────────────────────
    try:
        recalled = await recall_relevant_memories(user_id, context)
        context["recalled_memories"] = recalled
    except Exception:
        logger.exception("Memory recall failed for user %s", user_id)
        context["recalled_memories"] = []

    return context
