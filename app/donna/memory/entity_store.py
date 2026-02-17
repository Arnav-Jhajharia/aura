"""Entity store — structured queries over UserEntity rows."""

import logging

from sqlalchemy import select

from db.models import UserEntity
from db.session import async_session

logger = logging.getLogger(__name__)


async def get_top_entities(
    user_id: str, entity_type: str | None = None, limit: int = 10,
) -> list[dict]:
    """Get entities by mention_count descending. Optionally filter by type."""
    async with async_session() as session:
        stmt = select(UserEntity).where(UserEntity.user_id == user_id)
        if entity_type:
            stmt = stmt.where(UserEntity.entity_type == entity_type)
        stmt = stmt.order_by(UserEntity.mention_count.desc()).limit(limit)

        result = await session.execute(stmt)
        entities = result.scalars().all()

    return [
        {
            "name": e.name,
            "type": e.entity_type,
            "mention_count": e.mention_count,
            "last_mentioned": e.last_mentioned.isoformat() if e.last_mentioned else None,
            "metadata": e.metadata_,
        }
        for e in entities
    ]


async def get_entity_by_name(user_id: str, name: str) -> dict | None:
    """Look up an entity by normalized name (case-insensitive)."""
    normalized = name.strip().lower()
    async with async_session() as session:
        result = await session.execute(
            select(UserEntity).where(
                UserEntity.user_id == user_id,
                UserEntity.name_normalized == normalized,
            )
        )
        e = result.scalar_one_or_none()

    if not e:
        return None

    return {
        "name": e.name,
        "type": e.entity_type,
        "mention_count": e.mention_count,
        "first_mentioned": e.first_mentioned.isoformat() if e.first_mentioned else None,
        "last_mentioned": e.last_mentioned.isoformat() if e.last_mentioned else None,
        "metadata": e.metadata_,
        "sentiment": e.sentiment,
    }


async def get_recent_entities(user_id: str, limit: int = 10) -> list[dict]:
    """Get entities by last_mentioned descending."""
    async with async_session() as session:
        result = await session.execute(
            select(UserEntity)
            .where(UserEntity.user_id == user_id)
            .order_by(UserEntity.last_mentioned.desc())
            .limit(limit)
        )
        entities = result.scalars().all()

    return [
        {
            "name": e.name,
            "type": e.entity_type,
            "mention_count": e.mention_count,
            "last_mentioned": e.last_mentioned.isoformat() if e.last_mentioned else None,
        }
        for e in entities
    ]
