"""Context builder — assembles the full picture of a user's life for the LLM."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ChatMessage, Expense, MoodLog, Task
from db.session import async_session
from donna.brain.feedback import get_feedback_summary
from donna.brain.rules import count_proactive_today
from donna.memory.recall import recall_relevant_memories
from donna.signals.base import Signal
from donna.user_model import get_user_snapshot

logger = logging.getLogger(__name__)


async def build_context(
    user_id: str,
    signals: list[Signal],
    *,
    trust_info: dict | None = None,
) -> dict:
    """Build a complete context window for the brain's LLM call.

    Returns a dict with everything Donna needs to decide what to say:
    - user profile (from unified snapshot)
    - entities (from unified snapshot)
    - behaviors (from unified snapshot)
    - memory facts (from unified snapshot)
    - current signals
    - recent conversation
    - pending tasks
    - recent mood
    - today's spending
    - current time info
    - trust_info (trust level and config)
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

    # ── Unified user snapshot (profile, entities, behaviors, memory facts) ──
    try:
        snapshot = await get_user_snapshot(user_id)
    except Exception:
        logger.exception("Failed to load user snapshot for %s", user_id)
        snapshot = {}

    if not snapshot:
        return context

    context["user"] = snapshot.get("profile", {})
    context["user_stats"] = snapshot.get("stats", {})

    entities = snapshot.get("entities", {})
    context["key_people"] = entities.get("people", [])
    context["key_places"] = entities.get("places", [])
    context["recent_entities"] = entities.get("recent", [])

    context["user_behaviors"] = snapshot.get("behaviors", {})
    context["memory_facts"] = snapshot.get("memory_facts", [])

    # ── Context-specific queries (not part of user model) ──────────────

    async with async_session() as session:
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

    # ── Behavioral patterns from memory facts ─────────────────────────
    context["behavioral_patterns"] = [
        f["fact"] for f in context.get("memory_facts", [])
        if f.get("category") == "pattern"
    ]

    # ── Feedback summary ─────────────────────────────────────────────
    try:
        context["feedback_summary"] = await get_feedback_summary(user_id)
    except Exception:
        logger.exception("Feedback summary failed for user %s", user_id)
        context["feedback_summary"] = {}

    # ── Trust info (from prefilter) ───────────────────────────────────
    if trust_info:
        context["trust_info"] = trust_info
        context["score_threshold"] = trust_info.get("score_threshold", 5.5)

    # ── Feedback-derived preferences (from nightly reflection) ─────────
    behaviors = context.get("user_behaviors", {})
    if behaviors.get("category_preferences"):
        context["category_preferences"] = behaviors["category_preferences"]
    if behaviors.get("engagement_trends"):
        context["engagement_trends"] = behaviors["engagement_trends"]
    if behaviors.get("format_preferences"):
        context["format_preferences"] = behaviors["format_preferences"]
    if behaviors.get("send_time_preferences"):
        context["send_time_preferences"] = behaviors["send_time_preferences"]
    if behaviors.get("category_suppression"):
        context["category_suppression"] = behaviors["category_suppression"]
    # Meta-feedback overrides (from explicit user feedback)
    if behaviors.get("meta_format_preference"):
        context["meta_format_preference"] = behaviors["meta_format_preference"]
    # Suppressed categories from prefilter (trust_info carries it)
    if trust_info and trust_info.get("suppressed_categories"):
        context.setdefault("category_suppression", {}).setdefault("suppressed", {}).update(
            trust_info["suppressed_categories"]
        )

    return context
