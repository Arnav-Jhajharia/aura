"""Scorer and filter — applies hard rules and soft scoring to candidates."""

import logging
from datetime import datetime, timezone

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


def score_and_filter(candidates: list[dict], context: dict) -> list[dict]:
    """Score candidates, apply hard rules, return approved messages sorted by score.

    Returns only candidates that pass all filters, sorted best-first.
    """
    if not candidates:
        return []

    user = context.get("user", {})
    minutes_since_last = context.get("minutes_since_last_message")

    # ── Hard rule: quiet hours ───────────────────────────────────────
    now = datetime.now(timezone.utc)
    current_hour = now.hour  # TODO: convert to user's timezone

    wake_hour = int((user.get("wake_time") or "08:00").split(":")[0])
    sleep_hour = int((user.get("sleep_time") or "23:00").split(":")[0])

    in_quiet_hours = False
    if sleep_hour > wake_hour:
        # Normal: wake 8, sleep 23 → quiet = [23, 8)
        in_quiet_hours = current_hour >= sleep_hour or current_hour < wake_hour
    else:
        # Wraps midnight: wake 10, sleep 2 → quiet = [2, 10)
        in_quiet_hours = sleep_hour <= current_hour < wake_hour

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

        scored.append(candidate)

    # Sort by composite score descending
    scored.sort(key=lambda c: c["composite_score"], reverse=True)

    # ── Hard rule: daily cap ─────────────────────────────────────────
    # TODO: track actual messages sent today in DB; for now just cap the batch
    scored = scored[:MAX_PROACTIVE_PER_DAY]

    if scored:
        logger.info(
            "Approved %d/%d candidates (top: %.1f '%s')",
            len(scored),
            len(candidates),
            scored[0]["composite_score"],
            scored[0]["message"][:40],
        )

    return scored
