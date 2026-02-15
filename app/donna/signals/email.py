"""Email signal collector — checks Gmail via Composio."""

import logging

from donna.signals.base import Signal, SignalType
from tools.email import get_emails

logger = logging.getLogger(__name__)


async def collect_email_signals(user_id: str) -> list[Signal]:
    """Generate signals from the user's Gmail inbox."""
    signals: list[Signal] = []

    # Fetch unread emails
    unread = await get_emails(user_id=user_id, filter="unread", count=20)

    if unread and isinstance(unread[0], dict) and "error" in unread[0]:
        return []

    # ── Unread emails piling up ──────────────────────────────────────
    if len(unread) >= 5:
        signals.append(Signal(
            type=SignalType.EMAIL_UNREAD_PILING,
            user_id=user_id,
            data={
                "unread_count": len(unread),
                "subjects": [e.get("subject", "") for e in unread[:5]],
            },
        ))

    # ── Important / notable emails ───────────────────────────────────
    important = await get_emails(user_id=user_id, filter="important", count=5)

    if important and not (isinstance(important[0], dict) and "error" in important[0]):
        for email in important:
            signals.append(Signal(
                type=SignalType.EMAIL_IMPORTANT_RECEIVED,
                user_id=user_id,
                data={
                    "from": email.get("from", ""),
                    "subject": email.get("subject", ""),
                    "date": email.get("date", ""),
                    "snippet": email.get("snippet", ""),
                },
            ))

    return signals
