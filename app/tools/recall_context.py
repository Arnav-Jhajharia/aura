"""On-demand context loader — the planner calls this to fetch specific
context slices (tasks, moods, expenses, deadlines, deferred insights)
instead of dumping everything upfront.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import DeferredInsight, Expense, MoodLog, Task
from db.session import async_session

logger = logging.getLogger(__name__)


async def recall_context(user_id: str, entities: dict = None, **kwargs) -> dict | list:
    """Load a specific context slice on demand.

    The planner calls this with aspect = tasks | moods | deadlines | expenses | deferred_insights.
    """
    aspect = kwargs.get("aspect") or (entities or {}).get("aspect", "general")

    async with async_session() as session:
        if aspect == "tasks":
            result = await session.execute(
                select(Task)
                .where(Task.user_id == user_id, Task.status == "pending")
                .order_by(Task.due_date.asc().nullslast())
                .limit(20)
            )
            return [
                {
                    "title": t.title,
                    "due": t.due_date.isoformat() if t.due_date else None,
                    "priority": t.priority,
                    "source": t.source,
                }
                for t in result.scalars().all()
            ]

        elif aspect == "moods":
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
            result = await session.execute(
                select(MoodLog)
                .where(MoodLog.user_id == user_id, MoodLog.created_at >= cutoff)
                .order_by(MoodLog.created_at.desc())
            )
            moods = result.scalars().all()
            return {
                "entries": [
                    {"score": m.score, "note": m.note, "date": m.created_at.isoformat()}
                    for m in moods
                ],
                "average": round(sum(m.score for m in moods) / len(moods), 1) if moods else None,
            }

        elif aspect == "deadlines":
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
            result = await session.execute(
                select(Task)
                .where(
                    Task.user_id == user_id,
                    Task.status == "pending",
                    Task.due_date.isnot(None),
                    Task.due_date <= cutoff,
                )
                .order_by(Task.due_date.asc())
            )
            return [
                {"title": t.title, "due": t.due_date.isoformat(), "source": t.source}
                for t in result.scalars().all()
            ]

        elif aspect == "expenses":
            today = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
            result = await session.execute(
                select(Expense).where(Expense.user_id == user_id, Expense.created_at >= today)
            )
            expenses = result.scalars().all()
            return {
                "today_total": sum(e.amount for e in expenses),
                "items": [
                    {"amount": e.amount, "category": e.category, "desc": e.description}
                    for e in expenses
                ],
            }

        elif aspect == "deferred_insights":
            result = await session.execute(
                select(DeferredInsight)
                .where(
                    DeferredInsight.user_id == user_id,
                    DeferredInsight.used.is_(False),
                    DeferredInsight.expires_at >= datetime.now(timezone.utc).replace(tzinfo=None),
                )
                .order_by(DeferredInsight.relevance_score.desc())
                .limit(3)
            )
            insights = result.scalars().all()
            # Mark as used so they aren't surfaced again
            for d in insights:
                d.used = True
            await session.commit()
            return [
                {"message": d.message_draft, "category": d.category} for d in insights
            ]

    return {}
