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


async def get_email_detail(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Get the full body of a specific email by ID.

    Used when the user wants to read an email, not just see the subject line.
    """
    provider = await get_email_provider(user_id)
    if not provider:
        return {"error": "Email not connected."}

    email_id = kwargs.get("email_id", "")
    if not email_id:
        return {"error": "No email_id provided."}

    if provider == "microsoft":
        result = await execute_tool(
            slug="OUTLOOK_FETCH_EMAILS",
            user_id=user_id,
            arguments={"query": f"id eq '{email_id}'", "top": 1},
        )
    else:
        result = await execute_tool(
            slug="GMAIL_GET_EMAIL",
            user_id=user_id,
            arguments={"message_id": email_id},
        )

    if not result.get("successful"):
        return {"error": f"Failed to fetch email: {result.get('error', 'Unknown')}"}

    data = result.get("data", {})
    return {
        "id": data.get("id", email_id),
        "from": data.get("from", data.get("sender", "")),
        "to": data.get("to", ""),
        "subject": data.get("subject", ""),
        "date": data.get("date", data.get("receivedDateTime", "")),
        "body": data.get("body", data.get("snippet", data.get("bodyPreview", ""))),
    }


async def reply_to_email(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Reply to an email. Requires email_id and body text."""
    provider = await get_email_provider(user_id)
    if not provider:
        return {"error": "Email not connected."}

    email_id = kwargs.get("email_id", "")
    body = kwargs.get("body", "")
    if not email_id or not body:
        return {"error": "Need both email_id and body to reply."}

    if provider == "microsoft":
        result = await execute_tool(
            slug="OUTLOOK_REPLY_EMAIL",
            user_id=user_id,
            arguments={"message_id": email_id, "comment": body},
        )
    else:
        result = await execute_tool(
            slug="GMAIL_REPLY_TO_THREAD",
            user_id=user_id,
            arguments={"message_id": email_id, "body": body},
        )

    if not result.get("successful"):
        return {"error": f"Reply failed: {result.get('error', 'Unknown')}"}

    return {"success": True}


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
