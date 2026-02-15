import logging

import httpx
from sqlalchemy import select

from config import settings
from db.models import VoiceNote
from db.session import async_session

logger = logging.getLogger(__name__)


async def search_voice_notes(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Search over past voice notes by keyword (semantic search via pgvector TODO).

    For now, performs a simple text search on transcripts.
    """
    query = kwargs.get("query", "")

    async with async_session() as session:
        result = await session.execute(
            select(VoiceNote)
            .where(
                VoiceNote.user_id == user_id,
                VoiceNote.transcript.ilike(f"%{query}%"),
            )
            .order_by(VoiceNote.created_at.desc())
            .limit(10)
        )
        notes = result.scalars().all()

    return [
        {
            "id": n.id,
            "transcript_preview": (n.transcript or "")[:200],
            "date": n.created_at.isoformat(),
            "tags": n.tags,
            "duration_seconds": n.duration_seconds,
        }
        for n in notes
    ]


async def get_voice_note_summary(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Get full transcript and summary of a specific voice note."""
    voice_note_id = kwargs.get("voice_note_id", "")

    async with async_session() as session:
        result = await session.execute(
            select(VoiceNote).where(
                VoiceNote.id == voice_note_id,
                VoiceNote.user_id == user_id,
            )
        )
        note = result.scalar_one_or_none()

    if not note:
        return {"error": "Voice note not found"}

    return {
        "transcript": note.transcript,
        "summary": note.summary,
        "tags": note.tags,
        "date": note.created_at.isoformat(),
        "duration_seconds": note.duration_seconds,
    }
