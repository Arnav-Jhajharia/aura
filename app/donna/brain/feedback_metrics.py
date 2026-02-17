"""Nightly feedback metrics — deterministic computation from ProactiveFeedback data.

Computed by nightly reflection and stored as UserBehavior rows.
No LLM calls. Pure SQL aggregation + Python computation.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ProactiveFeedback, UserBehavior
from db.session import async_session
from donna.brain.feedback import OUTCOME_SCORES

logger = logging.getLogger(__name__)

# Recency decay half-life in days
HALF_LIFE_DAYS = 14
# Minimum data points per category/format before computing preference
MIN_SAMPLE_SIZE = 3
# Look-back window for feedback data
FEEDBACK_WINDOW_DAYS = 60


def _recency_weight(days_ago: float) -> float:
    """Exponential decay weight with 14-day half-life."""
    return 0.5 ** (days_ago / HALF_LIFE_DAYS)


async def _load_feedback(user_id: str, days: int = FEEDBACK_WINDOW_DAYS) -> list:
    """Load feedback entries for a user within the look-back window."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    async with async_session() as session:
        result = await session.execute(
            select(ProactiveFeedback)
            .where(
                ProactiveFeedback.user_id == user_id,
                ProactiveFeedback.sent_at >= cutoff,
                ProactiveFeedback.outcome.notin_(["pending", "undelivered"]),
            )
        )
        return result.scalars().all()


async def compute_category_preferences(user_id: str) -> dict:
    """Per-category engagement score with 14-day half-life recency decay.

    Returns:
        {"value": {"deadline_warning": 0.85, "wellbeing": 0.12, ...}, "sample_size": N}
    """
    entries = await _load_feedback(user_id)
    if not entries:
        return {"value": {}, "sample_size": 0}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    category_scores: dict[str, list[float]] = defaultdict(list)

    for entry in entries:
        cat = entry.category or "unknown"
        score = entry.feedback_score
        if score is None:
            score = OUTCOME_SCORES.get(entry.outcome)
        if score is None:
            continue

        days_ago = max(0, (now - entry.sent_at).total_seconds() / 86400)
        weight = _recency_weight(days_ago)
        category_scores[cat].append(score * weight)

    preferences = {}
    for cat, scores in category_scores.items():
        if len(scores) < MIN_SAMPLE_SIZE:
            continue
        raw = sum(scores) / len(scores)
        preferences[cat] = round(max(0.0, raw), 3)

    return {"value": preferences, "sample_size": len(entries)}


async def compute_engagement_trends(user_id: str) -> dict:
    """Compare engagement rates: this week vs last week vs 2 weeks ago.

    Returns:
        {"value": {"deadline_warning": {"current_rate": 0.8, "direction": "rising"}, ...},
         "sample_size": N}
    """
    entries = await _load_feedback(user_id, days=21)
    if not entries:
        return {"value": {}, "sample_size": 0}

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Bucket entries into 3 weeks
    buckets: dict[str, dict[str, dict]] = defaultdict(lambda: {
        "this_week": {"total": 0, "engaged": 0},
        "last_week": {"total": 0, "engaged": 0},
        "two_weeks": {"total": 0, "engaged": 0},
    })

    _engaged = {
        "engaged", "button_click", "positive_reply", "neutral_reply", "late_engage",
    }

    for entry in entries:
        cat = entry.category or "unknown"
        days_ago = (now - entry.sent_at).total_seconds() / 86400

        if days_ago <= 7:
            bucket = "this_week"
        elif days_ago <= 14:
            bucket = "last_week"
        else:
            bucket = "two_weeks"

        buckets[cat][bucket]["total"] += 1
        if entry.outcome in _engaged:
            buckets[cat][bucket]["engaged"] += 1

    trends = {}
    for cat, weeks in buckets.items():
        tw = weeks["this_week"]
        lw = weeks["last_week"]

        current_rate = tw["engaged"] / tw["total"] if tw["total"] >= 2 else None
        prev_rate = lw["engaged"] / lw["total"] if lw["total"] >= 2 else None

        if current_rate is None:
            continue

        if prev_rate is not None:
            diff = current_rate - prev_rate
            if diff >= 0.10:
                direction = "rising"
            elif diff <= -0.10:
                direction = "falling"
            else:
                direction = "stable"
        else:
            direction = "new"

        trends[cat] = {
            "current_rate": round(current_rate, 3),
            "direction": direction,
        }

    return {"value": trends, "sample_size": len(entries)}


async def compute_send_time_preferences(user_id: str) -> dict:
    """Hour-of-day engagement rates (UTC, timezone conversion done at injection).

    Returns:
        {"value": {"peak_hours": [9, 20], "avoid_hours": [14], "hourly_rates": {8: 0.6, ...}},
         "sample_size": N}
    """
    entries = await _load_feedback(user_id)
    if not entries:
        return {"value": {"peak_hours": [], "avoid_hours": [], "hourly_rates": {}}, "sample_size": 0}

    _engaged = {
        "engaged", "button_click", "positive_reply", "neutral_reply", "late_engage",
    }

    hourly: dict[int, dict] = defaultdict(lambda: {"total": 0, "engaged": 0})
    for entry in entries:
        if entry.sent_at:
            hour = entry.sent_at.hour
            hourly[hour]["total"] += 1
            if entry.outcome in _engaged:
                hourly[hour]["engaged"] += 1

    hourly_rates = {}
    for hour, stats in sorted(hourly.items()):
        if stats["total"] >= MIN_SAMPLE_SIZE:
            hourly_rates[hour] = round(stats["engaged"] / stats["total"], 3)

    if not hourly_rates:
        return {"value": {"peak_hours": [], "avoid_hours": [], "hourly_rates": {}}, "sample_size": len(entries)}

    # Top 3 hours by engagement rate
    sorted_hours = sorted(hourly_rates.items(), key=lambda x: x[1], reverse=True)
    peak_hours = [h for h, _ in sorted_hours[:3]]

    # Bottom 3 hours with sufficient data
    avoid_hours = [h for h, r in sorted_hours[-3:] if r < 0.3]

    return {
        "value": {
            "peak_hours": sorted(peak_hours),
            "avoid_hours": sorted(avoid_hours),
            "hourly_rates": hourly_rates,
        },
        "sample_size": len(entries),
    }


async def compute_format_preferences(user_id: str) -> dict:
    """Engagement rate by message format (text, button, list, template, etc.).

    Returns:
        {"value": {"preferred_format": "button", "format_rates": {"button": 0.85, ...}},
         "sample_size": N}
    """
    entries = await _load_feedback(user_id)
    if not entries:
        return {"value": {"preferred_format": None, "format_rates": {}}, "sample_size": 0}

    _engaged = {
        "engaged", "button_click", "positive_reply", "neutral_reply", "late_engage",
    }

    format_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "engaged": 0})
    for entry in entries:
        fmt = entry.format_used or "text"
        format_stats[fmt]["total"] += 1
        if entry.outcome in _engaged:
            format_stats[fmt]["engaged"] += 1

    format_rates = {}
    for fmt, stats in format_stats.items():
        if stats["total"] >= MIN_SAMPLE_SIZE:
            format_rates[fmt] = round(stats["engaged"] / stats["total"], 3)

    preferred = max(format_rates, key=format_rates.get) if format_rates else None

    return {
        "value": {"preferred_format": preferred, "format_rates": format_rates},
        "sample_size": len(entries),
    }


async def compute_adaptive_engagement_window(user_id: str) -> dict:
    """Per-user engagement window duration based on response speed.

    Window = max(30, median_response_minutes * 3), capped at 180.

    Returns:
        {"value": {"window_minutes": 45, "median_response_minutes": 12.5}, "sample_size": N}
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    async with async_session() as session:
        result = await session.execute(
            select(ProactiveFeedback.response_latency_seconds)
            .where(
                ProactiveFeedback.user_id == user_id,
                ProactiveFeedback.response_latency_seconds.isnot(None),
                ProactiveFeedback.sent_at >= cutoff,
            )
        )
        latencies = [row[0] for row in result.all()]

    if not latencies:
        return {
            "value": {"window_minutes": 60, "median_response_minutes": None},
            "sample_size": 0,
        }

    sorted_lat = sorted(latencies)
    median_seconds = sorted_lat[len(sorted_lat) // 2]
    median_minutes = median_seconds / 60

    window = max(30, median_minutes * 3)
    window = min(180, window)

    return {
        "value": {
            "window_minutes": round(window, 1),
            "median_response_minutes": round(median_minutes, 1),
        },
        "sample_size": len(latencies),
    }


async def compute_category_suppression(user_id: str) -> dict:
    """Check if any category should be suppressed based on feedback data.

    Suppression rules:
    - >= 5 sends and 0% engagement in the last 14 days → suppress
    - >= 3 negative replies in the last 14 days → suppress immediately

    Also handles probationary re-introduction after 21 days.

    Returns:
        {"value": {"suppressed": {"wellbeing": {...}, ...}}, "sample_size": N}
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=14)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with async_session() as session:
        result = await session.execute(
            select(ProactiveFeedback)
            .where(
                ProactiveFeedback.user_id == user_id,
                ProactiveFeedback.sent_at >= cutoff,
                ProactiveFeedback.outcome.notin_(["pending", "undelivered"]),
            )
        )
        entries = result.scalars().all()

        # Load existing suppressions
        sup_result = await session.execute(
            select(UserBehavior).where(
                UserBehavior.user_id == user_id,
                UserBehavior.behavior_key == "category_suppression",
            )
        )
        existing = sup_result.scalar_one_or_none()

    existing_value = existing.value if existing else {"suppressed": {}}
    suppressed = existing_value.get("suppressed", {})

    _engaged = {
        "engaged", "button_click", "positive_reply", "neutral_reply", "late_engage",
    }

    # Compute per-category stats
    cat_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "engaged": 0, "negative": 0})
    for entry in entries:
        cat = entry.category or "unknown"
        cat_stats[cat]["total"] += 1
        if entry.outcome in _engaged:
            cat_stats[cat]["engaged"] += 1
        if entry.outcome in ("negative_reply", "explicit_stop"):
            cat_stats[cat]["negative"] += 1

    # Check for new suppressions
    for cat, stats in cat_stats.items():
        if cat in suppressed:
            continue  # Already suppressed

        # Rule 1: >= 5 sends, 0% engagement
        if stats["total"] >= 5 and stats["engaged"] == 0:
            suppressed[cat] = {
                "since": now.isoformat(),
                "reason": "low_engagement",
                "probation_at": (now + timedelta(days=21)).isoformat(),
            }
            logger.info("Suppressing category '%s' for user %s (0%% engagement, %d sends)",
                         cat, user_id, stats["total"])

        # Rule 2: >= 3 negative replies
        elif stats["negative"] >= 3:
            suppressed[cat] = {
                "since": now.isoformat(),
                "reason": "negative_feedback",
                "probation_at": (now + timedelta(days=21)).isoformat(),
            }
            logger.info("Suppressing category '%s' for user %s (%d negative replies)",
                         cat, user_id, stats["negative"])

    # Check for probationary re-introduction
    for cat in list(suppressed.keys()):
        info = suppressed[cat]
        if info["reason"] == "explicit_stop":
            continue  # Never auto-reintroduce explicit stops

        probation_at = info.get("probation_at")
        if probation_at:
            try:
                prob_dt = datetime.fromisoformat(str(probation_at))
                if prob_dt <= now:
                    # Check if there was a recent positive engagement
                    cat_recent = cat_stats.get(cat, {})
                    if cat_recent.get("engaged", 0) > 0:
                        del suppressed[cat]
                        logger.info("Lifting suppression for '%s' (user %s, positive engagement)",
                                     cat, user_id)
                    else:
                        # Extend suppression for another 21 days
                        info["probation_at"] = (now + timedelta(days=21)).isoformat()
            except (ValueError, TypeError):
                pass

    return {
        "value": {"suppressed": suppressed},
        "sample_size": len(entries),
    }


# ── Registry for reflection.py ──────────────────────────────────────────────

FEEDBACK_COMPUTERS: dict[str, callable] = {
    "category_preferences": compute_category_preferences,
    "engagement_trends": compute_engagement_trends,
    "send_time_preferences": compute_send_time_preferences,
    "format_preferences": compute_format_preferences,
    "category_suppression": compute_category_suppression,
    "adaptive_engagement_window": compute_adaptive_engagement_window,
}
