"""Feedback loop — tracks which proactive messages users engage with."""

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ProactiveFeedback, UserBehavior, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)

# If user responds within this window after a proactive message, it counts as engagement
ENGAGEMENT_WINDOW_MINUTES = 60
# After this time with no response, mark as ignored
IGNORE_TIMEOUT_MINUTES = 180
# Late engagement: replied after window but before timeout
LATE_ENGAGE_MINUTES = IGNORE_TIMEOUT_MINUTES

# ── Outcome hierarchy: feedback scores ────────────────────────────────────────
OUTCOME_SCORES: dict[str, float | None] = {
    "positive_reply":  1.0,
    "button_click":    0.9,
    "neutral_reply":   0.7,
    "late_engage":     0.4,
    "read":            0.3,
    "delivered_only":  0.1,
    "ignored":         0.0,
    "negative_reply": -0.5,
    "explicit_stop":  -1.0,
    "undelivered":     None,
    "pending":         None,
}

# ── Sentiment classification (keyword-based V1) ──────────────────────────────

_POSITIVE_PATTERNS = [
    r"\bthanks?\b", r"\bthx\b", r"\bty\b", r"\bhelpful\b", r"\bgot it\b",
    r"\bperfect\b", r"\bnice\b", r"\bgood to know\b", r"\bappreciate\b",
    r"\bgreat\b", r"\bawesome\b", r"\bamazing\b", r"\blove it\b",
    r"👍", r"❤️", r"🙏", r"💯", r"🔥", r"😊", r"😄",
]

_NEGATIVE_PATTERNS = [
    r"\bstop\b", r"\bdon'?t\b.*\b(text|message|send|remind)\b",
    r"\bannoying\b", r"\bnot helpful\b", r"\bi know\b", r"\bleave me alone\b",
    r"\btoo many\b", r"\bspam\b", r"\bshut up\b", r"\bplease don'?t\b",
    r"\bstop sending\b", r"\bunsubscribe\b", r"\bgo away\b",
]

_EXPLICIT_STOP_PATTERNS = [
    r"\bstop\s+(sending|texting|messaging)\b",
    r"\bdon'?t\s+(ever\s+)?(text|message|send|remind)\s+me\b",
    r"\bleave\s+me\s+alone\b",
    r"\bunsubscribe\b",
]


def classify_reply_sentiment(reply_text: str) -> str:
    """Quick keyword-based sentiment classification of reply to proactive message.

    Returns: "positive" | "negative" | "neutral"
    """
    if not reply_text or not reply_text.strip():
        return "neutral"

    lower = reply_text.lower().strip()

    # Check negative first (higher priority — "thanks but stop" is negative)
    for pattern in _NEGATIVE_PATTERNS:
        if re.search(pattern, lower):
            return "negative"

    for pattern in _POSITIVE_PATTERNS:
        if re.search(pattern, lower):
            return "positive"

    return "neutral"


def is_explicit_stop(reply_text: str) -> bool:
    """Check if the reply is an explicit request to stop messaging."""
    if not reply_text:
        return False
    lower = reply_text.lower().strip()
    return any(re.search(p, lower) for p in _EXPLICIT_STOP_PATTERNS)


async def record_proactive_send(
    user_id: str,
    message_id: str,
    candidate: dict,
    wa_message_id: str | None = None,
    format_used: str | None = None,
    template_name: str | None = None,
) -> None:
    """Record that a proactive message was sent, for later feedback tracking."""
    async with async_session() as session:
        session.add(ProactiveFeedback(
            id=generate_uuid(),
            user_id=user_id,
            message_id=message_id,
            category=candidate.get("category", "nudge"),
            trigger_signals=candidate.get("trigger_signals", []),
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
            outcome="pending",
            wa_message_id=wa_message_id,
            format_used=format_used,
            template_name=template_name,
        ))
        await session.commit()


async def check_and_update_feedback(
    user_id: str, reply_text: str | None = None,
) -> None:
    """Check pending feedback entries and update outcomes.

    Called when user sends a message — if there's a recent pending proactive
    message, classify the reply sentiment and mark with a granular outcome.
    Also time out old pending entries as ignored.

    Args:
        user_id: The user who sent a message.
        reply_text: The text of the user's reply (for sentiment classification).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Load adaptive engagement window if available
    engagement_window = ENGAGEMENT_WINDOW_MINUTES
    ignore_timeout = IGNORE_TIMEOUT_MINUTES
    try:
        async with async_session() as session:
            aew_result = await session.execute(
                select(UserBehavior.value).where(
                    UserBehavior.user_id == user_id,
                    UserBehavior.behavior_key == "adaptive_engagement_window",
                )
            )
            aew_row = aew_result.scalar_one_or_none()
            if aew_row and isinstance(aew_row, dict):
                custom_window = aew_row.get("window_minutes")
                if custom_window:
                    engagement_window = min(custom_window, IGNORE_TIMEOUT_MINUTES)
                    ignore_timeout = max(engagement_window * 2, IGNORE_TIMEOUT_MINUTES)
    except Exception:
        pass  # use defaults

    engagement_cutoff = now - timedelta(minutes=engagement_window)
    late_cutoff = now - timedelta(minutes=ignore_timeout)
    ignore_cutoff = now - timedelta(minutes=ignore_timeout)

    # Classify sentiment if reply_text provided
    sentiment = classify_reply_sentiment(reply_text) if reply_text else None
    stop_requested = is_explicit_stop(reply_text) if reply_text else False

    async with async_session() as session:
        # Mark recent pending entries (within engagement window)
        recent_pending = await session.execute(
            select(ProactiveFeedback)
            .where(
                ProactiveFeedback.user_id == user_id,
                ProactiveFeedback.outcome == "pending",
                ProactiveFeedback.sent_at >= engagement_cutoff,
            )
        )
        for fb in recent_pending.scalars().all():
            fb.response_latency_seconds = (now - fb.sent_at).total_seconds()
            fb.reply_sentiment = sentiment

            if stop_requested:
                fb.outcome = "explicit_stop"
            elif sentiment == "negative":
                fb.outcome = "negative_reply"
            elif sentiment == "positive":
                fb.outcome = "positive_reply"
            else:
                fb.outcome = "neutral_reply"

            fb.feedback_score = OUTCOME_SCORES.get(fb.outcome)

        # Late engagement: pending entries between engagement window and timeout
        late_pending = await session.execute(
            select(ProactiveFeedback)
            .where(
                ProactiveFeedback.user_id == user_id,
                ProactiveFeedback.outcome == "pending",
                ProactiveFeedback.sent_at < engagement_cutoff,
                ProactiveFeedback.sent_at >= late_cutoff,
            )
        )
        for fb in late_pending.scalars().all():
            fb.response_latency_seconds = (now - fb.sent_at).total_seconds()
            fb.reply_sentiment = sentiment

            if stop_requested:
                fb.outcome = "explicit_stop"
                fb.feedback_score = OUTCOME_SCORES["explicit_stop"]
            elif sentiment == "negative":
                fb.outcome = "negative_reply"
                fb.feedback_score = OUTCOME_SCORES["negative_reply"]
            else:
                fb.outcome = "late_engage"
                fb.feedback_score = OUTCOME_SCORES["late_engage"]

        # Time out old pending entries (past timeout)
        old_pending = await session.execute(
            select(ProactiveFeedback)
            .where(
                ProactiveFeedback.user_id == user_id,
                ProactiveFeedback.outcome == "pending",
                ProactiveFeedback.sent_at < ignore_cutoff,
            )
        )
        for fb in old_pending.scalars().all():
            if fb.delivery_status == "failed":
                fb.outcome = "undelivered"
                fb.feedback_score = OUTCOME_SCORES["undelivered"]
            elif fb.delivery_status == "read":
                fb.outcome = "ignored"
                fb.feedback_score = OUTCOME_SCORES["ignored"]
            elif fb.delivery_status == "delivered":
                fb.outcome = "ignored"
                fb.feedback_score = OUTCOME_SCORES["delivered_only"]
            else:
                fb.outcome = "ignored"
                fb.feedback_score = OUTCOME_SCORES["ignored"]

        await session.commit()


async def get_feedback_summary(user_id: str, days: int = 30) -> dict:
    """Get engagement summary for the last N days.

    Returns:
        {
            "total_sent": int,
            "engaged": int,
            "ignored": int,
            "engagement_rate": float,
            "engagement_by_category": {"deadline_warning": 0.8, ...},
            "avg_response_latency_seconds": float | None,
        }
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    async with async_session() as session:
        result = await session.execute(
            select(ProactiveFeedback)
            .where(
                ProactiveFeedback.user_id == user_id,
                ProactiveFeedback.sent_at >= cutoff,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return {
            "total_sent": 0,
            "engaged": 0,
            "ignored": 0,
            "engagement_rate": 0.0,
            "engagement_by_category": {},
            "avg_response_latency_seconds": None,
        }

    total = len(entries)
    _engaged_outcomes = {
        "engaged", "button_click", "positive_reply", "neutral_reply", "late_engage",
    }
    engaged = sum(1 for e in entries if e.outcome in _engaged_outcomes)
    ignored = sum(1 for e in entries if e.outcome == "ignored")

    # Engagement by category
    category_counts: dict[str, dict] = {}
    for e in entries:
        cat = e.category or "unknown"
        if cat not in category_counts:
            category_counts[cat] = {"total": 0, "engaged": 0}
        category_counts[cat]["total"] += 1
        if e.outcome in _engaged_outcomes:
            category_counts[cat]["engaged"] += 1

    engagement_by_category = {
        cat: counts["engaged"] / counts["total"]
        for cat, counts in category_counts.items()
        if counts["total"] > 0
    }

    latencies = [e.response_latency_seconds for e in entries if e.response_latency_seconds]
    avg_latency = sum(latencies) / len(latencies) if latencies else None

    return {
        "total_sent": total,
        "engaged": engaged,
        "ignored": ignored,
        "engagement_rate": engaged / total if total else 0.0,
        "engagement_by_category": engagement_by_category,
        "avg_response_latency_seconds": avg_latency,
    }


# ── Meta-feedback detection ──────────────────────────────────────────────────

# Patterns that signal meta-feedback about Donna's proactive behavior.
# Each pattern maps to (action, target), where action is what to do and
# target is what it applies to (e.g. category name or behavior key).
_META_PATTERNS: list[tuple[str, str, str]] = [
    # Category boost
    (r"\b(reminders?|deadline)\b.*(helpful|useful|great|love|keep)", "boost", "deadline_warning"),
    (r"\b(schedule|calendar)\b.*(helpful|useful|great|love|keep)", "boost", "schedule_info"),
    (r"\b(nudge|push)\b.*(helpful|useful|great|love|keep)", "boost", "nudge"),
    # Category suppress
    (r"\bstop.*(sending|texting).*(wellbeing|check.?in)", "suppress", "wellbeing"),
    (r"\bstop.*(sending|texting).*(schedule|calendar)", "suppress", "schedule_info"),
    (r"\bstop.*(sending|texting).*(reminder|deadline)", "suppress", "deadline_warning"),
    (r"\bdon'?t.*(need|want).*(wellbeing|check.?in)", "suppress", "wellbeing"),
    (r"\bdon'?t.*(need|want).*(schedule|calendar)", "suppress", "schedule_info"),
    (r"\bdon'?t.*(need|want).*(reminder|deadline)", "suppress", "deadline_warning"),
    # Time preference
    (r"\b(text|message|send)\b.*\bearlier\b", "time_adjust", "earlier"),
    (r"\b(text|message|send)\b.*\blater\b", "time_adjust", "later"),
    (r"\b(text|message|send)\b.*\bmorning\b", "time_adjust", "morning"),
    (r"\b(text|message|send)\b.*\bevening\b", "time_adjust", "evening"),
    # Format preference
    (r"\bbuttons?\b.*(useful|helpful|great|prefer|like)", "format_pref", "button"),
    (r"\bshorter\b.*\bmessages?\b", "length_pref", "short"),
    (r"\blonger\b.*\bmessages?\b", "length_pref", "long"),
    # General stop
    (r"\bstop\s+(all|every)\b.*\b(message|text|notification)", "suppress_all", "all"),
    (r"\btoo\s+many\s+(message|text|notification)", "reduce_frequency", "all"),
]


def detect_meta_feedback(reply_text: str) -> list[dict]:
    """Detect meta-feedback about Donna's proactive behavior.

    Returns a list of detected meta-feedback signals, each with:
        {"action": str, "target": str, "pattern": str}
    """
    if not reply_text or not reply_text.strip():
        return []

    lower = reply_text.lower().strip()
    results = []

    for pattern, action, target in _META_PATTERNS:
        if re.search(pattern, lower):
            results.append({
                "action": action,
                "target": target,
                "pattern": pattern,
            })

    return results


async def apply_meta_feedback(user_id: str, meta_signals: list[dict]) -> None:
    """Store meta-feedback as high-confidence UserBehavior entries.

    Meta-feedback overrides computed preferences immediately.
    """
    if not meta_signals:
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with async_session() as session:
        for signal in meta_signals:
            action = signal["action"]

            if action == "suppress":
                # Immediate category suppression via meta-feedback
                key = "category_suppression"
                existing = await session.execute(
                    select(UserBehavior).where(
                        UserBehavior.user_id == user_id,
                        UserBehavior.behavior_key == key,
                    )
                )
                behavior = existing.scalar_one_or_none()
                value = behavior.value if behavior else {"suppressed": {}}

                value.setdefault("suppressed", {})
                value["suppressed"][signal["target"]] = {
                    "since": now.isoformat(),
                    "reason": "explicit_stop",
                    "probation_at": None,
                }

                if behavior:
                    behavior.value = value
                    behavior.confidence = 1.0
                    behavior.last_computed = now
                else:
                    session.add(UserBehavior(
                        id=generate_uuid(),
                        user_id=user_id,
                        behavior_key=key,
                        value=value,
                        confidence=1.0,
                        sample_size=1,
                        last_computed=now,
                    ))

            elif action == "boost":
                # Boost category preference (stored as meta override)
                key = "meta_category_overrides"
                existing = await session.execute(
                    select(UserBehavior).where(
                        UserBehavior.user_id == user_id,
                        UserBehavior.behavior_key == key,
                    )
                )
                behavior = existing.scalar_one_or_none()
                value = behavior.value if behavior else {}

                value[signal["target"]] = {
                    "boost": True,
                    "since": now.isoformat(),
                }

                if behavior:
                    behavior.value = value
                    behavior.confidence = 1.0
                    behavior.last_computed = now
                else:
                    session.add(UserBehavior(
                        id=generate_uuid(),
                        user_id=user_id,
                        behavior_key=key,
                        value=value,
                        confidence=1.0,
                        sample_size=1,
                        last_computed=now,
                    ))

            elif action == "format_pref":
                key = "meta_format_preference"
                existing = await session.execute(
                    select(UserBehavior).where(
                        UserBehavior.user_id == user_id,
                        UserBehavior.behavior_key == key,
                    )
                )
                behavior = existing.scalar_one_or_none()
                value = {"preferred_format": signal["target"], "since": now.isoformat()}

                if behavior:
                    behavior.value = value
                    behavior.confidence = 1.0
                    behavior.last_computed = now
                else:
                    session.add(UserBehavior(
                        id=generate_uuid(),
                        user_id=user_id,
                        behavior_key=key,
                        value=value,
                        confidence=1.0,
                        sample_size=1,
                        last_computed=now,
                    ))

            logger.info("Meta-feedback applied for user %s: %s → %s", user_id, action, signal["target"])

        await session.commit()
