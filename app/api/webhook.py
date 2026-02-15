import logging

from fastapi import APIRouter, Request, Response

from agent.graph import process_message
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


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
            # Status update or other non-message event
            return Response(status_code=200)

        message = messages[0]
        sender_phone = message["from"]
        message_type = message["type"]  # text, audio, image, location

        # Extract content based on message type
        if message_type == "text":
            raw_input = message["text"]["body"]
            media_id = None
        elif message_type == "audio":
            raw_input = ""
            media_id = message["audio"]["id"]
        elif message_type == "image":
            raw_input = message.get("image", {}).get("caption", "")
            media_id = message["image"]["id"]
        elif message_type == "interactive":
            # Button reply — treat the button id as the raw input
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
                raw_input = interactive["button_reply"]["id"]
            elif interactive.get("type") == "list_reply":
                raw_input = interactive["list_reply"]["id"]
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
        )

    except Exception:
        logger.exception("Error processing webhook message")

    # Always return 200 to acknowledge receipt
    return Response(status_code=200)
