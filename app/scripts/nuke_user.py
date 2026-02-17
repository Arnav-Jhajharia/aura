"""One-shot script: delete a user and ALL their data by phone number."""

import asyncio
import sys

from sqlalchemy import delete, select

from db.models import (
    ChatMessage, DeferredInsight, DeferredSend, Expense, Habit,
    JournalEntry, MemoryFact, MoodLog, OAuthToken, ProactiveFeedback,
    SignalState, Task, User, UserBehavior, UserEntity, VoiceNote,
)
from db.session import async_session

CHILD_TABLES = [
    ChatMessage, DeferredInsight, DeferredSend, Expense, Habit,
    JournalEntry, MemoryFact, MoodLog, OAuthToken, ProactiveFeedback,
    SignalState, Task, UserBehavior, UserEntity, VoiceNote,
]


async def nuke(phone: str) -> None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if not user:
            print(f"No user found with phone {phone}")
            return

        uid = user.id
        print(f"Found user: id={uid}, name={user.name}, phone={phone}")
        print(f"Created: {user.created_at}, onboarding: {user.onboarding_complete}")

        for model in CHILD_TABLES:
            res = await session.execute(
                delete(model).where(model.user_id == uid)
            )
            if res.rowcount:
                print(f"  Deleted {res.rowcount} rows from {model.__tablename__}")

        await session.execute(delete(User).where(User.id == uid))
        print(f"  Deleted user row")

        await session.commit()
        print(f"\nDone. User {phone} fully nuked.")


if __name__ == "__main__":
    phone = sys.argv[1] if len(sys.argv) > 1 else "+919875486045"
    if not phone.startswith("+"):
        phone = "+" + phone
    asyncio.run(nuke(phone))
