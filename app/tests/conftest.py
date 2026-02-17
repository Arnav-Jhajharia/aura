"""Shared fixtures for Donna tests.

Uses an in-memory SQLite database via SQLAlchemy async (aiosqlite).
Patches `async_session` in all modules that import it so production code
transparently hits the test DB instead of Postgres.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import (
    Base,
    ChatMessage,
    Habit,
    MemoryFact,
    MoodLog,
    SignalState,  # noqa: F401 — imported so create_all() builds its table
    Task,
    User,
    generate_uuid,
)

# All modules that do `from db.session import async_session`
_MODULES_USING_SESSION = [
    "db.session",
    "donna.signals.internal",
    "donna.signals.calendar",
    "donna.signals.canvas",
    "donna.signals.email",
    "donna.signals.dedup",
    "donna.signals.collector",
    "donna.brain.context",
    "donna.brain.sender",
    "donna.brain.rules",
    "donna.memory.entities",
    "donna.memory.recall",
    "donna.memory.patterns",
    "tools.memory_search",
    "agent.nodes.memory",
]


@pytest_asyncio.fixture()
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def patch_async_session(db_engine):
    """Patch async_session in ALL modules that import it."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    patches = []
    for mod in _MODULES_USING_SESSION:
        try:
            p = patch(f"{mod}.async_session", factory)
            p.start()
            patches.append(p)
        except AttributeError:
            pass  # Module doesn't import async_session (yet)
    yield factory
    for p in patches:
        p.stop()


# ── Factory helpers ────────────────────────────────────────────────────────

def make_user(**overrides) -> User:
    defaults = {
        "id": generate_uuid(),
        "phone": "+1234567890",
        "name": "Test User",
        "timezone": "Asia/Singapore",
        "wake_time": "08:00",
        "sleep_time": "23:00",
        "reminder_frequency": "normal",
        "tone_preference": "casual",
        "onboarding_complete": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def make_chat_message(user_id: str, role: str = "user", content: str = "hello",
                      created_at: datetime | None = None) -> ChatMessage:
    return ChatMessage(
        id=generate_uuid(),
        user_id=user_id,
        role=role,
        content=content,
        created_at=created_at or datetime.now(timezone.utc),
    )


def make_memory_fact(user_id: str, fact: str = "likes pizza",
                     category: str = "preference", **overrides) -> MemoryFact:
    defaults = {
        "id": generate_uuid(),
        "user_id": user_id,
        "fact": fact,
        "category": category,
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return MemoryFact(**defaults)


def make_task(user_id: str, title: str = "Do homework", **overrides) -> Task:
    defaults = {
        "id": generate_uuid(),
        "user_id": user_id,
        "title": title,
        "status": "pending",
        "priority": 2,
        "source": "manual",
    }
    defaults.update(overrides)
    return Task(**defaults)


def make_mood(user_id: str, score: int = 6, **overrides) -> MoodLog:
    defaults = {
        "id": generate_uuid(),
        "user_id": user_id,
        "score": score,
        "source": "manual",
    }
    defaults.update(overrides)
    return MoodLog(**defaults)


def make_habit(user_id: str, name: str = "Gym", **overrides) -> Habit:
    defaults = {
        "id": generate_uuid(),
        "user_id": user_id,
        "name": name,
        "target_frequency": "daily",
        "current_streak": 5,
        "longest_streak": 10,
    }
    defaults.update(overrides)
    return Habit(**defaults)
