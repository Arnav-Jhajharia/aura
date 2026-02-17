import logging

from sqlalchemy import select

from agent.state import AuraState
from db.models import ChatMessage, User, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)

HISTORY_WINDOW = 6  # 3 turns = 6 messages (user + assistant)


async def message_ingress(state: AuraState) -> dict:
    """Parse incoming WhatsApp message and resolve the user.

    - Looks up or creates the user by phone number.
    - Loads user preferences (timezone, reminder settings, tone).
    - Loads last 3 conversation turns so the classifier has history.
    - Populates user_id and initial state fields.
    """
    phone = state["phone"]

    async with async_session() as session:
        result = await session.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(id=generate_uuid(), phone=phone)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info("Created new user %s for phone %s", user.id, phone)

        # Load last 3 turns of conversation history for classifier context
        history_result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(HISTORY_WINDOW)
        )
        history_rows = history_result.scalars().all()

    conversation_history = [
        {"role": m.role, "content": m.content}
        for m in reversed(history_rows)
    ]

    return {
        "user_id": user.id,
        "onboarding_step": user.onboarding_step,
        "pending_action": user.pending_action,
        "user_context": {
            "timezone": user.timezone,
            "wake_time": user.wake_time,
            "sleep_time": user.sleep_time,
            "reminder_frequency": user.reminder_frequency,
            "tone_preference": user.tone_preference,
            "onboarding_complete": user.onboarding_complete,
            "conversation_history": conversation_history,
        },
    }
