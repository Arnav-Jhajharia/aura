import logging

from tools.composio_client import execute_tool, get_email_provider

logger = logging.getLogger(__name__)


async def get_emails(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Get emails from Gmail or Outlook via Composio."""
    provider = await get_email_provider(user_id)
    if not provider:
        return [{"error": "Email not connected. Send /connect google or /connect microsoft to set up."}]

    email_filter = kwargs.get("filter", "unread")
    count = kwargs.get("count", 10)

    if provider == "microsoft":
        odata_map = {
            "unread": "isRead eq false",
            "important": "importance eq 'high' and isRead eq false",
            "all": "",
        }
        q = odata_map.get(email_filter, "isRead eq false")
        result = await execute_tool(
            slug="OUTLOOK_FETCH_EMAILS",
            user_id=user_id,
            arguments={"query": q, "top": count},
        )
    else:
        query_map = {
            "unread": "is:unread",
            "important": "is:important is:unread",
            "all": "",
        }
        q = query_map.get(email_filter, "is:unread")
        result = await execute_tool(
            slug="GMAIL_FETCH_EMAILS",
            user_id=user_id,
            arguments={"query": q, "max_results": count},
        )

    if not result.get("successful"):
        error = str(result.get("error", "Unknown error"))
        if "not connected" in error.lower() or "no connected account" in error.lower():
            return [{"error": "Email not connected. Send /connect google or /connect microsoft to set up."}]
        return [{"error": f"Email API error: {error}"}]

    data = result.get("data", {})
    messages = data.get("messages", data) if isinstance(data, dict) else data

    if isinstance(messages, list):
        return [
            {
                "id": msg.get("id", ""),
                "from": msg.get("from", msg.get("sender", "")),
                "subject": msg.get("subject", ""),
                "date": msg.get("date", msg.get("receivedDateTime", "")),
                "snippet": msg.get("snippet", msg.get("preview", msg.get("bodyPreview", ""))),
            }
            for msg in messages[:count]
        ]

    return [data] if data else []


async def send_email(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Send an email via Gmail or Outlook through Composio."""
    provider = await get_email_provider(user_id)
    if not provider:
        return {"error": "Email not connected."}

    to = kwargs.get("to", "")
    subject = kwargs.get("subject", "")
    body = kwargs.get("body", "")

    if provider == "microsoft":
        result = await execute_tool(
            slug="OUTLOOK_SEND_EMAIL",
            user_id=user_id,
            arguments={"to": to, "subject": subject, "body": body},
        )
    else:
        result = await execute_tool(
            slug="GMAIL_SEND_EMAIL",
            user_id=user_id,
            arguments={"to": to, "subject": subject, "body": body},
        )

    if not result.get("successful"):
        error = str(result.get("error", "Unknown error"))
        if "not connected" in error.lower() or "no connected account" in error.lower():
            return {"error": "Email not connected."}
        return {"error": f"Failed to send: {error}"}

    return {"success": True, "message_id": result.get("data", {}).get("id", "")}
