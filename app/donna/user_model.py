"""Unified user model snapshot — single function to get the full picture of a user."""

import logging

from sqlalchemy import select

from db.models import MemoryFact, User, UserBehavior, UserEntity
from db.session import async_session

logger = logging.getLogger(__name__)


async def get_user_snapshot(user_id: str) -> dict:
    """Assemble the complete user model for any layer to consume.

    Returns:
        {
            "profile": { ... },
            "entities": { "people": [...], "places": [...], "recent": [...] },
            "behaviors": { "active_hours": {...}, ... },
            "memory_facts": [...],
            "stats": { ... },
        }
    """
    async with async_session() as session:
        # ── User profile ───────────────────────────────────────────────
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            return {}

        profile = {
            "name": user.name or "",
            "timezone": user.timezone or "UTC",
            "wake_time": user.wake_time or "08:00",
            "sleep_time": user.sleep_time or "23:00",
            "reminder_frequency": user.reminder_frequency or "normal",
            "tone_preference": user.tone_preference or "casual",
            "academic_year": getattr(user, "academic_year", None),
            "faculty": getattr(user, "faculty", None),
            "major": getattr(user, "major", None),
            "graduation_year": getattr(user, "graduation_year", None),
        }

        stats = {
            "total_messages": getattr(user, "total_messages", 0) or 0,
            "proactive_engagement_rate": getattr(user, "proactive_engagement_rate", None),
            "avg_response_latency_seconds": getattr(user, "avg_response_latency_seconds", None),
            "last_active_at": (
                user.last_active_at.isoformat()
                if getattr(user, "last_active_at", None)
                else None
            ),
            "has_canvas": getattr(user, "has_canvas", False),
            "has_google": getattr(user, "has_google", False),
            "has_microsoft": getattr(user, "has_microsoft", False),
            "nusmods_imported": getattr(user, "nusmods_imported", False),
        }

        # ── Entities ───────────────────────────────────────────────────
        people_result = await session.execute(
            select(UserEntity)
            .where(UserEntity.user_id == user_id, UserEntity.entity_type == "person")
            .order_by(UserEntity.mention_count.desc())
            .limit(10)
        )
        people = [
            {"name": e.name, "mention_count": e.mention_count}
            for e in people_result.scalars().all()
        ]

        places_result = await session.execute(
            select(UserEntity)
            .where(UserEntity.user_id == user_id, UserEntity.entity_type == "place")
            .order_by(UserEntity.mention_count.desc())
            .limit(10)
        )
        places = [
            {"name": e.name, "mention_count": e.mention_count}
            for e in places_result.scalars().all()
        ]

        recent_result = await session.execute(
            select(UserEntity)
            .where(UserEntity.user_id == user_id)
            .order_by(UserEntity.last_mentioned.desc())
            .limit(10)
        )
        recent = [
            {"name": e.name, "type": e.entity_type, "mention_count": e.mention_count}
            for e in recent_result.scalars().all()
        ]

        # ── Behaviors ──────────────────────────────────────────────────
        beh_result = await session.execute(
            select(UserBehavior).where(UserBehavior.user_id == user_id)
        )
        behaviors = {b.behavior_key: b.value for b in beh_result.scalars().all()}

        # ── Memory facts ───────────────────────────────────────────────
        facts_result = await session.execute(
            select(MemoryFact)
            .where(MemoryFact.user_id == user_id)
            .order_by(MemoryFact.created_at.desc())
            .limit(20)
        )
        memory_facts = [
            {"fact": f.fact, "category": f.category, "confidence": f.confidence}
            for f in facts_result.scalars().all()
        ]

    return {
        "profile": profile,
        "entities": {"people": people, "places": places, "recent": recent},
        "behaviors": behaviors,
        "memory_facts": memory_facts,
        "stats": stats,
    }
