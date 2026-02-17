import logging
from dataclasses import dataclass

import httpx

from config import settings

logger = logging.getLogger(__name__)

WA_API_BASE = "https://graph.facebook.com/v18.0"

# ── WhatsAppResult ────────────────────────────────────────────────────────────

@dataclass
class WhatsAppResult:
    success: bool = False
    wa_message_id: str | None = None
    error_code: int | None = None
    error_message: str | None = None
    retryable: bool = False
    fallback_format: str | None = None

_RETRYABLE_CODES = {130472}  # rate limit
_FALLBACK_CODES = {131051}   # unsupported message type


def parse_wa_response(resp_json: dict, http_status: int) -> WhatsAppResult:
    """Parse a WhatsApp Cloud API response into a WhatsAppResult."""
    if not isinstance(resp_json, dict):
        return WhatsAppResult(error_message="malformed response")

    # Success: {"messages": [{"id": "wamid.xxx"}]}
    messages = resp_json.get("messages")
    if isinstance(messages, list) and messages:
        wa_id = messages[0].get("id") if isinstance(messages[0], dict) else None
        return WhatsAppResult(success=True, wa_message_id=wa_id)

    # Error: {"error": {"code": ..., "message": ...}}
    error = resp_json.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        msg = error.get("message", "")
        retryable = code in _RETRYABLE_CODES if isinstance(code, int) else False
        fallback = "text" if (isinstance(code, int) and code in _FALLBACK_CODES) else None
        return WhatsAppResult(
            error_code=code, error_message=msg,
            retryable=retryable, fallback_format=fallback,
        )

    # Non-200 with no parseable structure
    if http_status != 200:
        return WhatsAppResult(error_message=f"HTTP {http_status}", retryable=True)

    return WhatsAppResult(error_message="unknown response structure")


# ── Connection pool ───────────────────────────────────────────────────────────

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.whatsapp_token}"}


def _url() -> str:
    return f"{WA_API_BASE}/{settings.whatsapp_phone_number_id}/messages"


async def _post(json_body: dict) -> WhatsAppResult:
    """Post to WhatsApp API and return a structured result."""
    try:
        resp = await _get_client().post(_url(), headers=_headers(), json=json_body)
        result = parse_wa_response(resp.json(), resp.status_code)
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("WhatsApp API error: %s", exc)
        return WhatsAppResult(error_message=str(exc), retryable=True)
    if not result.success:
        logger.error("WhatsApp send failed: code=%s msg=%s", result.error_code, result.error_message)
    return result


# ── Send functions ────────────────────────────────────────────────────────────

async def send_whatsapp_message(to: str, text: str) -> WhatsAppResult:
    """Send a text message via WhatsApp Business API."""
    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    })


async def send_whatsapp_template(
    to: str,
    template_name: str,
    params: list[str],
    button_payloads: list[str] | None = None,
) -> WhatsAppResult:
    """Send a template message (for proactive outreach outside 24h window)."""
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
                "index": i,
                "parameters": [{"type": "payload", "payload": payload}],
            })

    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
            "components": components,
        },
    })


async def send_whatsapp_buttons(to: str, body: str, buttons: list[dict]) -> WhatsAppResult:
    """Send a reply-button interactive message."""
    return await _post({
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
    })


async def send_whatsapp_cta_button(
    to: str, body: str, button_text: str, url: str,
) -> WhatsAppResult:
    """Send a single CTA URL button message."""
    return await _post({
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
    })


async def send_whatsapp_list(
    to: str,
    body: str,
    button_text: str,
    sections: list[dict],
) -> WhatsAppResult:
    """Send an interactive list message."""
    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button_text,
                "sections": sections,
            },
        },
    })


async def react_to_message(to: str, message_id: str, emoji: str = "\U0001f44d") -> WhatsAppResult:
    """Send a reaction (emoji) to a specific WhatsApp message."""
    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "reaction",
        "reaction": {
            "message_id": message_id,
            "emoji": emoji,
        },
    })


async def download_media(media_id: str) -> bytes:
    """Download media (voice notes, images) from WhatsApp."""
    headers = _headers()
    client = _get_client()
    try:
        resp = await client.get(f"{WA_API_BASE}/{media_id}", headers=headers)
        resp.raise_for_status()
        media_url = resp.json()["url"]

        media_resp = await client.get(media_url, headers=headers)
        media_resp.raise_for_status()
        return media_resp.content
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Media download failed: %s", exc)
        raise
