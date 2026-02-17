import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

WA_API_BASE = "https://graph.facebook.com/v18.0"


async def send_whatsapp_message(to: str, text: str):
    """Send a text message via WhatsApp Business API."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WA_API_BASE}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
        )
        if resp.status_code != 200:
            logger.error("Failed to send WhatsApp message: %s", resp.text)
        return resp.json()


async def send_whatsapp_template(
    to: str,
    template_name: str,
    params: list[str],
    button_payloads: list[str] | None = None,
):
    """Send a template message (for proactive outreach outside 24h window).

    If button_payloads is provided, quick-reply button components are appended
    so WhatsApp can route tap callbacks back to us.
    """
    components = [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params],
        }
    ]
    if button_payloads:
        for i, payload in enumerate(button_payloads):
            components.append({
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(i),
                "parameters": [{"type": "payload", "payload": payload}],
            })

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WA_API_BASE}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": "en"},
                    "components": components,
                },
            },
        )
        return resp.json()


async def send_whatsapp_buttons(to: str, body: str, buttons: list[dict]):
    """Send a reply-button interactive message.

    buttons format: [{"id": "btn_id", "title": "Label"}, ...]  (max 3)
    When the user taps a button, WhatsApp sends back an interactive/button_reply message
    with the button id as raw_input.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WA_API_BASE}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                            for b in buttons
                        ]
                    },
                },
            },
        )
        if resp.status_code != 200:
            logger.error("Failed to send reply buttons: %s", resp.text)
        return resp.json()


async def send_whatsapp_cta_button(to: str, body: str, button_text: str, url: str):
    """Send a single CTA URL button message (WhatsApp interactive/cta_url)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WA_API_BASE}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "cta_url",
                    "body": {"text": body},
                    "action": {
                        "name": "cta_url",
                        "parameters": {
                            "display_text": button_text,
                            "url": url,
                        },
                    },
                },
            },
        )
        if resp.status_code != 200:
            logger.error("Failed to send CTA button: %s", resp.text)
        return resp.json()


async def download_media(media_id: str) -> bytes:
    """Download media (voice notes, images) from WhatsApp."""
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}

    async with httpx.AsyncClient() as client:
        # Get media URL
        resp = await client.get(f"{WA_API_BASE}/{media_id}", headers=headers)
        resp.raise_for_status()
        media_url = resp.json()["url"]

        # Download the file
        media_resp = await client.get(media_url, headers=headers)
        media_resp.raise_for_status()
        return media_resp.content
