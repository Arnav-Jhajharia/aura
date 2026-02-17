import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import JournalEntry, MoodLog, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)


async def save_journal_entry(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Save a journal entry (reflection, gratitude, brain_dump, vent)."""
    entry_type = kwargs.get("entry_type", "brain_dump")
    content = kwargs.get("content", "")
    mood_score = kwargs.get("mood_score")

    entry = JournalEntry(
        id=generate_uuid(),
        user_id=user_id,
        entry_type=entry_type,
        content=content,
        mood_score=mood_score,
    )

    async with async_session() as session:
        session.add(entry)
        await session.commit()

    return {
        "id": entry.id,
        "entry_type": entry_type,
        "mood_score": mood_score,
    }


async def log_mood(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Log a mood score (1-10) with optional note."""
    score = kwargs.get("score", 5)
    note = kwargs.get("note", "")

    mood = MoodLog(
        id=generate_uuid(),
        user_id=user_id,
        score=score,
        note=note,
    )

    async with async_session() as session:
        session.add(mood)
        await session.commit()

        # Calculate trend
        seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
        result = await session.execute(
            select(MoodLog)
            .where(MoodLog.user_id == user_id, MoodLog.created_at >= seven_days_ago)
            .order_by(MoodLog.created_at.desc())
        )
        recent = result.scalars().all()
        avg = sum(m.score for m in recent) / len(recent) if recent else score

    return {
        "score": score,
        "trend_7d_avg": round(avg, 1),
        "entries_this_week": len(recent),
    }


async def get_mood_history(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Get mood history for the last N days."""
    days = kwargs.get("days", 7)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    async with async_session() as session:
        result = await session.execute(
            select(MoodLog)
            .where(MoodLog.user_id == user_id, MoodLog.created_at >= cutoff)
            .order_by(MoodLog.created_at.desc())
        )
        moods = result.scalars().all()

    return [
        {
            "score": m.score,
            "note": m.note,
            "date": m.created_at.isoformat(),
        }
        for m in moods
    ]
