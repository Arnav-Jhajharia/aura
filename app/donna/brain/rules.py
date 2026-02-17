"""Scorer and filter — applies hard rules and soft scoring to candidates."""

import logging
import zoneinfo
from datetime import datetime, timezone

from sqlalchemy import select, func

from db.models import ChatMessage
from db.session import async_session

logger = logging.getLogger(__name__)

# Weights for composite score
W_RELEVANCE = 0.4
W_TIMING = 0.35
W_URGENCY = 0.25

# Thresholds
SCORE_THRESHOLD = 5.5          # minimum composite score to send
COOLDOWN_MINUTES = 30          # min gap between proactive messages
MAX_PROACTIVE_PER_DAY = 4      # max proactive messages per day
URGENT_SCORE_OVERRIDE = 8.5    # bypass cooldown if score is this high


def _get_local_hour(user: dict) -> int:
    """Get current hour in the user's timezone."""
    tz_name = user.get("timezone", "UTC")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        tz = timezone.utc
    return datetime.now(tz).hour


def score_and_filter(candidates: list[dict], context: dict) -> list[dict]:
    """Score candidates, apply hard rules, return approved messages sorted by score.

    Returns only candidates that pass all filters, sorted best-first.
    """
    if not candidates:
        return []

    user = context.get("user", {})
    minutes_since_last = context.get("minutes_since_last_message")

    # ── Hard rule: quiet hours (in user's timezone) ────────────────
    current_hour = _get_local_hour(user)

    wake_hour = int((user.get("wake_time") or "08:00").split(":")[0])
    sleep_hour = int((user.get("sleep_time") or "23:00").split(":")[0])

    in_quiet_hours = False
    if sleep_hour > wake_hour:
        # Normal: wake 8, sleep 23 → quiet = [23, 8)
        in_quiet_hours = current_hour >= sleep_hour or current_hour < wake_hour
    else:
        # Wraps midnight: wake 10, sleep 2 → quiet = [2, 10)
        in_quiet_hours = sleep_hour <= current_hour < wake_hour

    # ── Check daily cap from DB ────────────────────────────────────
    sent_today = context.get("proactive_sent_today", 0)

    # ── Recent assistant messages for dedup ─────────────────────────
    recent_messages = [
        m["content"].lower()
        for m in context.get("recent_conversation", [])
        if m.get("role") == "assistant"
    ]

    scored: list[dict] = []

    for candidate in candidates:
        relevance = candidate.get("relevance", 5)
        timing = candidate.get("timing", 5)
        urgency = candidate.get("urgency", 5)

        composite = (
            relevance * W_RELEVANCE
            + timing * W_TIMING
            + urgency * W_URGENCY
        )
        candidate["composite_score"] = round(composite, 2)

        # ── Filter: quiet hours (only override for truly urgent) ─────
        if in_quiet_hours and composite < URGENT_SCORE_OVERRIDE:
            logger.debug("Filtered (quiet hours): %s", candidate["message"][:50])
            continue

        # ── Filter: score threshold ──────────────────────────────────
        if composite < SCORE_THRESHOLD:
            logger.debug("Filtered (low score %.1f): %s", composite, candidate["message"][:50])
            continue

        # ── Filter: cooldown (unless very urgent) ────────────────────
        if minutes_since_last is not None and minutes_since_last < COOLDOWN_MINUTES:
            if composite < URGENT_SCORE_OVERRIDE:
                logger.debug(
                    "Filtered (cooldown %dm): %s",
                    int(minutes_since_last),
                    candidate["message"][:50],
                )
                continue

        # ── Filter: dedup (skip if similar to recent assistant message) ──
        candidate_lower = candidate["message"].lower()
        candidate_words = set(candidate_lower.split())
        is_duplicate = False
        for recent in recent_messages:
            recent_words = set(recent.split())
            if not candidate_words or not recent_words:
                continue
            overlap = len(candidate_words & recent_words) / max(len(candidate_words), 1)
            if overlap > 0.6:
                logger.debug("Filtered (dedup %.0f%% overlap): %s", overlap * 100, candidate["message"][:50])
                is_duplicate = True
                break
        if is_duplicate:
            continue

        scored.append(candidate)

    # Sort by composite score descending
    scored.sort(key=lambda c: c["composite_score"], reverse=True)

    # ── Hard rule: daily cap ─────────────────────────────────────────
    remaining_cap = max(0, MAX_PROACTIVE_PER_DAY - sent_today)
    scored = scored[:remaining_cap]

    if scored:
        logger.info(
            "Approved %d/%d candidates (top: %.1f '%s')",
            len(scored),
            len(candidates),
            scored[0]["composite_score"],
            scored[0]["message"][:40],
        )

    return scored


async def count_proactive_today(user_id: str) -> int:
    """Count how many proactive (assistant) messages were sent today."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as session:
        result = await session.execute(
            select(func.count(ChatMessage.id))
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "assistant",
                ChatMessage.is_proactive.is_(True),
                ChatMessage.created_at >= today_start,
            )
        )
        return result.scalar_one()
