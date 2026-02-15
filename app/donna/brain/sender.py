"""Sender — delivers approved messages via WhatsApp and logs them."""

import logging

from sqlalchemy import select

from db.models import ChatMessage, User, generate_uuid
from db.session import async_session
from tools.whatsapp import send_whatsapp_message

logger = logging.getLogger(__name__)


async def send_proactive_message(user_id: str, candidate: dict) -> bool:
    """Send a single proactive message to the user via WhatsApp.

    Also persists it as a ChatMessage so it shows in conversation history
    and the cooldown tracker can see it.

    Returns True if sent successfully.
    """
    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

    if not user or not user.phone:
        logger.warning("Cannot send proactive message: user %s not found or no phone", user_id)
        return False

    message_text = candidate["message"]

    try:
        await send_whatsapp_message(to=user.phone, text=message_text)
    except Exception:
        logger.exception("Failed to send proactive message to %s", user.phone)
        return False

    # Persist as assistant message in chat history
    async with async_session() as session:
        session.add(ChatMessage(
            id=generate_uuid(),
            user_id=user_id,
            role="assistant",
            content=message_text,
        ))
        await session.commit()

    logger.info(
        "Sent proactive message to %s (score=%.1f, category=%s): %s",
        user.phone,
        candidate.get("composite_score", 0),
        candidate.get("category", "unknown"),
        message_text[:60],
    )
    return True
