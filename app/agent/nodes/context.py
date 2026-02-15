import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from agent.state import AuraState
from config import settings
from db.models import ChatMessage, Expense, MemoryFact, MoodLog, OAuthToken, Task
from db.session import async_session
from tools.composio_client import get_connected_integrations

HISTORY_WINDOW = 10  # last 10 messages (5 user + 5 assistant turns)

logger = logging.getLogger(__name__)


async def context_loader(state: AuraState) -> dict:
    """Load relevant user context from the database based on intent.

    Pulls:
    - connected_integrations — Google from Composio, Canvas from OAuthToken
    - Pending tasks
    - Recent mood scores (last 7 days)
    - Today's expenses
    - Upcoming deadlines
    """
    user_id = state["user_id"]
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    context = {**state.get("user_context", {})}

    # Google integrations from Composio (handles Gmail + Calendar)
    connected = await get_connected_integrations(user_id)

    async with async_session() as session:
        # Canvas integration from OAuthToken (uses direct httpx, not Composio)
        canvas_result = await session.execute(
            select(OAuthToken.provider).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == "canvas",
            )
        )
        if canvas_result.scalar_one_or_none():
            connected.append("canvas")

        context["connected_integrations"] = connected  # e.g. ["google", "canvas"] or []

        # Canonical instructions for connecting integrations (when not connected)
        if "canvas" not in connected:
            context["canvas_connection_instructions"] = (
                "1. Open Canvas → Account → Settings\n"
                "2. Scroll to Approved Integrations\n"
                "3. Tap New Access Token → set a name, add an expiry\n"
                "4. Copy the token and paste it here in this chat."
            )
        if "google" not in connected:
            context["google_connection_url"] = (
                f"{settings.api_base_url}/auth/google/login?user_id={user_id}"
            )
            context["google_connection_instructions"] = (
                "Tap this link to connect Calendar and Gmail."
            )

        # Pending tasks
        tasks_result = await session.execute(
            select(Task)
            .where(Task.user_id == user_id, Task.status == "pending")
            .order_by(Task.due_date.asc().nullslast())
            .limit(20)
        )
        tasks = tasks_result.scalars().all()
        context["pending_tasks"] = [
            {
                "id": t.id,
                "title": t.title,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "priority": t.priority,
            }
            for t in tasks
        ]

        # Recent mood
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
        if moods:
            context["avg_mood"] = sum(m.score for m in moods) / len(moods)

        # Upcoming deadlines (next 7 days)
        deadline_cutoff = now + timedelta(days=7)
        deadline_result = await session.execute(
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.status == "pending",
                Task.due_date.isnot(None),
                Task.due_date <= deadline_cutoff,
            )
            .order_by(Task.due_date.asc())
        )
        deadlines = deadline_result.scalars().all()
        context["upcoming_deadlines"] = [
            {"title": t.title, "due_date": t.due_date.isoformat(), "source": t.source}
            for t in deadlines
        ]

        # Today's expenses
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        expense_result = await session.execute(
            select(Expense)
            .where(Expense.user_id == user_id, Expense.created_at >= today_start)
        )
        expenses = expense_result.scalars().all()
        context["today_spending"] = sum(e.amount for e in expenses)

        # Conversation history (last N messages)
        history_result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(HISTORY_WINDOW)
        )
        history_rows = history_result.scalars().all()
        context["conversation_history"] = [
            {"role": m.role, "content": m.content}
            for m in reversed(history_rows)
        ]

        # Long-term memory facts (most recent)
        facts_result = await session.execute(
            select(MemoryFact)
            .where(MemoryFact.user_id == user_id)
            .order_by(MemoryFact.created_at.desc())
            .limit(15)
        )
        facts = facts_result.scalars().all()
        context["memory_facts"] = [
            {"fact": f.fact, "category": f.category}
            for f in facts
        ]

    return {"user_context": context}
