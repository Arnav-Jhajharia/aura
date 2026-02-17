"""Simulation-specific fixtures — extends base conftest.

The base conftest.py (in tests/) handles DB setup and module patching.
This file adds simulation helpers.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone

from db.models import ChatMessage, MoodLog, Task, User, Habit, generate_uuid
from tests.simulation.archetypes import Archetype


@pytest_asyncio.fixture
async def sim_db(patch_async_session):
    """Expose the patched session factory for simulation use."""
    return patch_async_session


async def create_sim_user(session_factory, archetype: Archetype, user_id: str) -> User:
    """Create a User in the test DB matching the archetype profile."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    created_at = now - timedelta(days=archetype.initial_days_active)

    user = User(
        id=user_id,
        phone=f"+6591{hash(user_id) % 10000000:07d}",
        name=f"Sim {archetype.name.title()}",
        timezone=archetype.timezone,
        wake_time=archetype.wake_time,
        sleep_time=archetype.sleep_time,
        tone_preference="casual",
        reminder_frequency="normal",
        onboarding_complete=True,
        created_at=created_at,
    )

    async with session_factory() as session:
        session.add(user)
        await session.commit()

    # Seed initial messages to set trust level
    if archetype.initial_message_count > 0:
        async with session_factory() as session:
            for i in range(min(archetype.initial_message_count, 50)):
                msg_time = created_at + timedelta(
                    hours=i * (archetype.initial_days_active * 24 / max(archetype.initial_message_count, 1))
                )
                session.add(ChatMessage(
                    id=generate_uuid(),
                    user_id=user_id,
                    role="user",
                    content=f"sim seed message {i}",
                    created_at=msg_time,
                ))
            await session.commit()

    # Seed mood logs
    async with session_factory() as session:
        for d in range(min(archetype.initial_days_active, 7)):
            session.add(MoodLog(
                id=generate_uuid(),
                user_id=user_id,
                score=archetype.mood_score(d),
                source="manual",
                created_at=now - timedelta(days=d),
            ))
        await session.commit()

    # Seed a habit
    async with session_factory() as session:
        session.add(Habit(
            id=generate_uuid(),
            user_id=user_id,
            name="gym",
            target_frequency="daily",
            current_streak=5,
            longest_streak=10,
        ))
        await session.commit()

    return user


async def create_user_message(
    session_factory, user_id: str, text: str, created_at: datetime
) -> ChatMessage:
    """Simulate the user sending a message at a given time."""
    msg = ChatMessage(
        id=generate_uuid(),
        user_id=user_id,
        role="user",
        content=text,
        created_at=created_at.replace(tzinfo=None) if created_at.tzinfo else created_at,
    )
    async with session_factory() as session:
        session.add(msg)
        await session.commit()
    return msg
