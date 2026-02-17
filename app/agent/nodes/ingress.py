import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from agent.state import AuraState
from db.models import ChatMessage, User, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)

# Expanded history window: 10 turns = 20 messages (user + assistant).
# Classifier still uses the last 6 for speed; planner and composer get the full 20.
HISTORY_WINDOW = 20


async def message_ingress(state: AuraState) -> dict:
    """Parse incoming WhatsApp message and resolve the user.

    - Looks up or creates the user by phone number.
    - Loads user preferences (timezone, reminder settings, tone).
    - Loads last 10 conversation turns so the planner has context.
    - Loads conversation summary (compressed older history) if available.
    - Loads pending multi-turn flow state if active.
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

        # Load last 10 turns of conversation history
        history_result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(HISTORY_WINDOW)
        )
        history_rows = history_result.scalars().all()

        # Load pending flow state (multi-turn context)
        pending_flow = None
        if user.pending_flow_json:
            try:
                flow = user.pending_flow_json
                # Expire flows older than 5 minutes
                expires_at = flow.get("expires_at")
                if expires_at:
                    exp = datetime.fromisoformat(expires_at)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) < exp:
                        pending_flow = flow
                    else:
                        # Expired — clear it
                        user.pending_flow_json = None
                        await session.commit()
                else:
                    pending_flow = flow
            except Exception:
                logger.debug("Failed to parse pending flow, ignoring")

        # Load conversation summary
        conversation_summary = getattr(user, "conversation_summary", None) or ""

    conversation_history = [
        {"role": m.role, "content": m.content}
        for m in reversed(history_rows)
    ]

    out: dict = {
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
            "conversation_summary": conversation_summary,
        },
    }

    if pending_flow:
        out["_pending_flow"] = pending_flow

    return out
