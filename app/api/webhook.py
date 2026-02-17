import asyncio
import logging
import time

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from agent.graph import process_message
from config import settings
from db.models import ProactiveFeedback
from db.session import async_session

logger = logging.getLogger(__name__)
router = APIRouter()

# Delivery status rank — never regress
_STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3, "failed": 0}

# ── Webhook dedup (Meta sends duplicate webhooks) ─────────────────────────
# Simple in-memory set with TTL. Stores (wa_message_id, timestamp).
# Protected by asyncio.Lock to prevent race conditions from concurrent webhooks.
_SEEN_MSG_IDS: dict[str, float] = {}
_DEDUP_TTL = 60  # seconds
_DEDUP_LOCK = asyncio.Lock()


async def _is_duplicate(wa_message_id: str | None) -> bool:
    """Return True if we've already processed this message ID recently."""
    if not wa_message_id:
        return False

    async with _DEDUP_LOCK:
        now = time.monotonic()

        # Prune expired entries (keep it bounded)
        expired = [k for k, ts in _SEEN_MSG_IDS.items() if now - ts > _DEDUP_TTL]
        for k in expired:
            del _SEEN_MSG_IDS[k]

        if wa_message_id in _SEEN_MSG_IDS:
            logger.debug("Duplicate webhook for message %s — skipping", wa_message_id)
            return True

        _SEEN_MSG_IDS[wa_message_id] = now
        return False


async def _handle_status_update(status: dict) -> None:
    """Process a WhatsApp delivery status update."""
    wa_message_id = status.get("id")
    status_name = status.get("status")
    if not wa_message_id or not status_name:
        return

    async with async_session() as session:
        result = await session.execute(
            select(ProactiveFeedback)
            .where(ProactiveFeedback.wa_message_id == wa_message_id)
        )
        fb = result.scalar_one_or_none()
        if not fb:
            return

        current_rank = _STATUS_RANK.get(fb.delivery_status, 1)
        new_rank = _STATUS_RANK.get(status_name)

        if new_rank is None:
            return

        # "failed" always sets regardless of current status
        if status_name == "failed":
            fb.delivery_status = "failed"
            errors = status.get("errors", [])
            if errors and isinstance(errors[0], dict):
                code = errors[0].get("code", "")
                title = errors[0].get("title", "")
                fb.delivery_failed_reason = f"{code}: {title}"
        elif new_rank > current_rank:
            fb.delivery_status = status_name

        await session.commit()


@router.get("/webhook")
async def verify_webhook(
    request: Request,
):
    """WhatsApp webhook verification (GET challenge-response)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("Webhook verified successfully")
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


@router.post("/webhook")
async def receive_message(request: Request):
    """Process incoming WhatsApp messages."""
    body = await request.json()

    # Extract message data from the webhook payload
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Process delivery status updates
            statuses = value.get("statuses", [])
            for s in statuses:
                try:
                    await _handle_status_update(s)
                except Exception:
                    logger.exception("Error processing status update")
            return Response(status_code=200)

        message = messages[0]
        sender_phone = message.get("from")
        if not sender_phone:
            logger.warning("Webhook message missing 'from' field")
            return Response(status_code=200)

        # Extract WhatsApp profile name from contacts array
        contacts = value.get("contacts", [])
        wa_profile_name = None
        if contacts and isinstance(contacts[0], dict):
            profile = contacts[0].get("profile", {})
            wa_profile_name = profile.get("name") if isinstance(profile, dict) else None

        wa_message_id = message.get("id")

        # Dedup: Meta often sends the same webhook twice
        if await _is_duplicate(wa_message_id):
            return Response(status_code=200)

        message_type = message.get("type")
        if not message_type:
            logger.warning("Webhook message missing 'type' field")
            return Response(status_code=200)

        # Extract content based on message type
        if message_type == "text":
            text_obj = message.get("text")
            raw_input = text_obj.get("body", "") if isinstance(text_obj, dict) else ""
            media_id = None
        elif message_type == "audio":
            raw_input = ""
            audio_obj = message.get("audio")
            media_id = audio_obj.get("id") if isinstance(audio_obj, dict) else None
        elif message_type == "image":
            image_obj = message.get("image", {})
            raw_input = image_obj.get("caption", "") if isinstance(image_obj, dict) else ""
            media_id = image_obj.get("id") if isinstance(image_obj, dict) else None
        elif message_type == "interactive":
            # Button reply — treat the button id as the raw input
            interactive = message.get("interactive", {})
            itype = interactive.get("type") if isinstance(interactive, dict) else None
            if itype == "button_reply":
                reply_obj = interactive.get("button_reply", {})
                raw_input = reply_obj.get("id", "") if isinstance(reply_obj, dict) else ""
            elif itype == "list_reply":
                reply_obj = interactive.get("list_reply", {})
                raw_input = reply_obj.get("id", "") if isinstance(reply_obj, dict) else ""
            else:
                raw_input = ""
            media_id = None
            message_type = "text"  # route through normal text pipeline
        else:
            raw_input = ""
            media_id = None

        # Run through LangGraph agent
        await process_message(
            agent=request.app.state.agent,
            phone=sender_phone,
            message_type=message_type,
            raw_input=raw_input,
            media_id=media_id,
            wa_message_id=wa_message_id,
            wa_profile_name=wa_profile_name,
        )

    except Exception:
        logger.exception("Error processing webhook message")

    # Always return 200 to acknowledge receipt
    return Response(status_code=200)
