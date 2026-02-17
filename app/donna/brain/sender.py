"""Sender — delivers approved messages via WhatsApp and logs them.

Routes through freeform text (inside 24h window) or pre-approved templates
(outside 24h window) based on the user's last interaction time.

Format selection is deterministic: text, button, list, or CTA URL based on
the candidate's category and content shape.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ChatMessage, User, UserBehavior, generate_uuid
from db.session import async_session
from donna.brain.feedback import record_proactive_send
from donna.brain.template_filler import fill_template_params
from donna.brain.validators import validate_format_constraints, validate_message, validate_template_params
from tools.whatsapp import (
    WhatsAppResult,
    send_whatsapp_buttons,
    send_whatsapp_cta_button,
    send_whatsapp_list,
    send_whatsapp_message,
    send_whatsapp_template,
)

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
    "habit": "donna_habit_streak",
    "exam_reminder": "donna_exam_reminder",
    "class_reminder": "donna_class_reminder",
}

# Templates that have quick-reply buttons registered
TEMPLATES_WITH_BUTTONS = {
    "donna_deadline_v2": ["got_it", "remind_later"],
    "donna_daily_digest": ["thanks", "tell_more"],
    "donna_check_in": ["yes", "not_now"],
    "donna_task_reminder": ["done", "snooze"],
}

# Safety margin: need at least this many minutes left in the 24h window
# to safely send freeform messages (avoid race condition with window closing)
WINDOW_SAFETY_MARGIN_MINUTES = 5


def _truncate_at_word_boundary(text: str, max_len: int) -> str:
    """Truncate text at the last word boundary within max_len."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]
    return truncated


async def _get_window_status(user_id: str) -> dict:
    """Check the 24h WhatsApp service window status for a user.

    Returns:
        {
            "open": bool,
            "minutes_remaining": float,
            "safe_for_freeform": bool,
            "last_user_message_at": datetime | None,
        }
    """
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
        last_msg_at = result.scalar_one_or_none()

    if last_msg_at is None:
        return {
            "open": False,
            "minutes_remaining": 0,
            "safe_for_freeform": False,
            "last_user_message_at": None,
        }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window_end = last_msg_at + timedelta(hours=24)
    minutes_remaining = (window_end - now).total_seconds() / 60

    is_open = minutes_remaining > 0
    safe = is_open and minutes_remaining > WINDOW_SAFETY_MARGIN_MINUTES

    return {
        "open": is_open,
        "minutes_remaining": max(0, minutes_remaining),
        "safe_for_freeform": safe,
        "last_user_message_at": last_msg_at,
    }


def _select_message_format(candidate: dict, context: dict | None = None) -> str:
    """Determine the best WhatsApp message format for this candidate.

    Considers the candidate's action_type and category, then biases toward
    the user's preferred format if available from feedback data.
    """
    action_type = candidate.get("action_type", "text")
    category = candidate.get("category", "nudge")
    message = candidate.get("message", "")

    if action_type == "button_prompt":
        return "button"

    if category == "briefing" and message.count("\n") >= 3:
        return "list"

    data = candidate.get("data", {})
    if isinstance(data, dict) and category in ("grade_alert", "email_alert") and data.get("link"):
        return "cta_url"

    # Bias toward user's preferred format if available
    if context:
        meta_fmt = context.get("meta_format_preference", {})
        fmt_pref = context.get("format_preferences", {})
        preferred = meta_fmt.get("preferred_format") or fmt_pref.get("preferred_format")

        if preferred == "button" and action_type != "text":
            return "button"

    return "text"


def _build_briefing_sections(message: str) -> tuple[str, str, list[dict]]:
    """Parse a briefing message into list message sections.

    Returns (body_text, button_text, sections).
    """
    lines = [line.strip() for line in message.split("\n") if line.strip()]
    if not lines:
        return (message, "View details", [])

    body = lines[0]
    rows = []
    for i, line in enumerate(lines[1:], start=1):
        uid = generate_uuid()[:8]
        title = _truncate_at_word_boundary(line, 24)
        description = line[len(title):].strip() if len(line) > len(title) else ""
        description = _truncate_at_word_boundary(description, 72)
        rows.append({
            "id": f"{uid}_{i}",
            "title": title,
            "description": description,
        })

    sections = [{"title": "Schedule", "rows": rows[:10]}]
    return (body, "View schedule", sections)


async def _send_freeform(phone: str, candidate: dict, fmt: str) -> WhatsAppResult:
    """Send a freeform message in the specified format."""
    message_text = candidate["message"]

    if fmt == "button":
        return await send_whatsapp_buttons(
            to=phone,
            body=message_text,
            buttons=[
                {"id": "btn_yes", "title": "Yes"},
                {"id": "btn_later", "title": "Later"},
            ],
        )
    elif fmt == "list":
        body, button_text, sections = _build_briefing_sections(message_text)
        if sections and sections[0].get("rows"):
            return await send_whatsapp_list(
                to=phone, body=body,
                button_text=button_text, sections=sections,
            )
        else:
            return await send_whatsapp_message(to=phone, text=message_text)
    elif fmt == "cta_url":
        data = candidate.get("data", {})
        link = data.get("link", "") if isinstance(data, dict) else ""
        if link:
            return await send_whatsapp_cta_button(
                to=phone, body=message_text,
                button_text="Open", url=link,
            )
        else:
            return await send_whatsapp_message(to=phone, text=message_text)
    else:
        return await send_whatsapp_message(to=phone, text=message_text)


async def send_with_retry(
    phone: str, candidate: dict, fmt: str, max_retries: int = 2,
) -> WhatsAppResult:
    """Send with format validation, fallback, and retry on transient errors."""
    # 1. Validate format constraints — fall back to text if invalid
    valid, reason = validate_format_constraints(candidate, fmt)
    if not valid:
        logger.warning("Format %s invalid (%s), falling back to text", fmt, reason)
        fmt = "text"

    # 2. First attempt
    result = await _send_freeform(phone, candidate, fmt)
    if result.success:
        return result

    # 3. If fallback_format suggested and not already text, try text
    if result.fallback_format and fmt != "text":
        logger.info("Falling back from %s to text for %s", fmt, phone)
        result = await _send_freeform(phone, candidate, "text")
        if result.success:
            return result

    # 4. Retry on transient errors with exponential backoff
    if result.retryable:
        for attempt in range(1, max_retries + 1):
            delay = 2 ** attempt
            logger.info("Retry %d/%d after %ds for %s", attempt, max_retries, delay, phone)
            await asyncio.sleep(delay)
            result = await _send_freeform(phone, candidate, "text")
            if result.success:
                return result

    return result


async def send_proactive_message(user_id: str, candidate: dict) -> bool:
    """Send a single proactive message to the user via WhatsApp.

    - Inside 24h window (safe) → freeform (text / button / list / CTA)
    - Outside or near-expiry → approved template message

    Also persists it as a ChatMessage and records feedback.
    Returns True if sent successfully.
    """
    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

    if not user or not user.phone:
        logger.warning("Cannot send proactive message: user %s not found or no phone", user_id)
        return False

    message_text = candidate["message"]

    # Pre-send validation
    message_text, warnings = validate_message(message_text)
    if not message_text:
        logger.warning("Message validation emptied message for user %s: %s", user_id, warnings)
        return False
    candidate["message"] = message_text

    window = await _get_window_status(user_id)
    fmt = None
    template_name = None

    # Load format preferences for format selection
    fmt_context: dict = {}
    try:
        async with async_session() as session:
            for key in ("format_preferences", "meta_format_preference"):
                result = await session.execute(
                    select(UserBehavior.value).where(
                        UserBehavior.user_id == user_id,
                        UserBehavior.behavior_key == key,
                    )
                )
                row = result.scalar_one_or_none()
                if row and isinstance(row, dict):
                    fmt_context[key] = row
    except Exception:
        pass  # graceful degradation

    try:
        if window["safe_for_freeform"]:
            fmt = _select_message_format(candidate, fmt_context)
            result = await send_with_retry(user.phone, candidate, fmt)
        else:
            # Outside 24h window or near expiry — must use approved template
            category = candidate.get("category", "nudge")
            template_name = CATEGORY_TEMPLATE_MAP.get(category, "donna_check_in")
            params = await fill_template_params(candidate, template_name)
            params = validate_template_params(params)
            button_payloads = TEMPLATES_WITH_BUTTONS.get(template_name)
            result = await send_whatsapp_template(
                to=user.phone,
                template_name=template_name,
                params=params,
                button_payloads=button_payloads,
            )
            fmt = "template"
    except Exception:
        logger.exception("Failed to send proactive message to %s", user.phone)
        return False

    if not result.success:
        logger.error(
            "Proactive message delivery failed for %s: code=%s msg=%s",
            user.phone, result.error_code, result.error_message,
        )
        return False

    # Persist as assistant message in chat history
    message_id = generate_uuid()
    async with async_session() as session:
        session.add(ChatMessage(
            id=message_id,
            user_id=user_id,
            role="assistant",
            content=message_text,
            is_proactive=True,
            wa_message_id=result.wa_message_id,
        ))
        await session.commit()

    # Record for feedback tracking
    try:
        await record_proactive_send(
            user_id, message_id, candidate,
            wa_message_id=result.wa_message_id,
            format_used=fmt,
            template_name=template_name,
        )
    except Exception:
        logger.exception("Failed to record proactive feedback for user %s", user_id)

    logger.info(
        "Sent proactive message to %s [%s] (score=%.1f, category=%s): %s",
        user.phone,
        fmt or "unknown",
        candidate.get("composite_score", 0),
        candidate.get("category", "unknown"),
        message_text[:60],
    )
    return True
