"""Sender — delivers approved messages via WhatsApp and logs them.

Routes through freeform text (inside 24h window) or pre-approved templates
(outside 24h window) based on the user's last interaction time.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ChatMessage, User, generate_uuid
from db.session import async_session
from tools.whatsapp import send_whatsapp_message, send_whatsapp_template

logger = logging.getLogger(__name__)

# Map Donna candidate categories → approved template names
CATEGORY_TEMPLATE_MAP = {
    "deadline_warning": "donna_deadline_v2",
    "schedule_info": "donna_schedule",
    "task_reminder": "donna_task_reminder",
    "wellbeing": "donna_check_in",
    "social": "donna_check_in",
    "nudge": "donna_study_nudge",
    "briefing": "donna_daily_digest",
    "memory_recall": "donna_check_in",
    "email_alert": "donna_email_alert",
    "grade_alert": "donna_grade_alert",
}

# Templates that have quick-reply buttons registered
TEMPLATES_WITH_BUTTONS = {
    "donna_deadline_v2": ["got_it", "remind_later"],
    "donna_daily_digest": ["thanks", "tell_more"],
    "donna_check_in": ["yes", "not_now"],
    "donna_task_reminder": ["done", "snooze"],
}


async def _is_window_open(user_id: str) -> bool:
    """Check if the user messaged within the last 24 hours (WhatsApp service window)."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    async with async_session() as session:
        result = await session.execute(
            select(ChatMessage.created_at)
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= cutoff,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


def _extract_template_params(candidate: dict, template_name: str) -> list[str]:
    """Split a candidate message into template variable slots.

    Each template expects a specific number of {{N}} variables.
    We split the LLM-generated message into that many parts.
    """
    msg = candidate["message"]

    # Number of variables each template expects
    var_counts = {
        "donna_deadline_v2": 2,       # assignment, due time
        "donna_grade_alert": 2,    # course, score
        "donna_schedule": 2,       # event, time+location
        "donna_daily_digest": 1,   # formatted schedule
        "donna_study_nudge": 1,    # suggestion
        "donna_email_alert": 1,    # summary
        "donna_check_in": 1,       # context
        "donna_task_reminder": 1,  # task description
    }

    expected = var_counts.get(template_name, 2)

    if expected == 1:
        return [msg]

    # Split on ". " to get sentence-level chunks, then group into expected slots
    parts = [p.strip() for p in msg.split(". ") if p.strip()]

    if len(parts) >= expected:
        # Take first (expected-1) parts individually, join the rest as the last param
        result = parts[: expected - 1]
        result.append(". ".join(parts[expected - 1 :]))
        return result

    # Pad with empty strings if message is shorter than expected
    return (parts + [""] * expected)[:expected]


async def send_proactive_message(user_id: str, candidate: dict) -> bool:
    """Send a single proactive message to the user via WhatsApp.

    - Inside 24h window → freeform text (full Donna voice)
    - Outside 24h window → approved template message

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
    window_open = await _is_window_open(user_id)

    try:
        if window_open:
            # Inside 24h window — send freeform Donna-voice message
            await send_whatsapp_message(to=user.phone, text=message_text)
        else:
            # Outside 24h window — must use approved template
            category = candidate.get("category", "nudge")
            template_name = CATEGORY_TEMPLATE_MAP.get(category, "donna_check_in")
            params = _extract_template_params(candidate, template_name)
            button_payloads = TEMPLATES_WITH_BUTTONS.get(template_name)
            await send_whatsapp_template(
                to=user.phone,
                template_name=template_name,
                params=params,
                button_payloads=button_payloads,
            )
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
            is_proactive=True,
        ))
        await session.commit()

    logger.info(
        "Sent proactive message to %s [%s] (score=%.1f, category=%s): %s",
        user.phone,
        "freeform" if window_open else "template",
        candidate.get("composite_score", 0),
        candidate.get("category", "unknown"),
        message_text[:60],
    )
    return True
