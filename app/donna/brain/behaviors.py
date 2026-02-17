"""Behavioral model — deterministic computation of user behavioral patterns.

No LLM calls. Pure SQL aggregation + Python computation.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ChatMessage, ProactiveFeedback
from db.session import async_session

logger = logging.getLogger(__name__)

# Outcomes that count as "engaged" across the system
_ENGAGED_OUTCOMES = {
    "engaged", "button_click", "positive_reply", "neutral_reply", "late_engage",
}


async def compute_active_hours(user_id: str) -> dict:
    """Compute peak activity hours from message timestamps."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    async with async_session() as session:
        result = await session.execute(
            select(ChatMessage.created_at)
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= cutoff,
            )
        )
        timestamps = [row[0] for row in result.all() if row[0]]

    if not timestamps:
        return {"value": {"peak_hours": [], "distribution": {}}, "sample_size": 0}

    hour_counts = Counter(ts.hour for ts in timestamps)
    total = sum(hour_counts.values())
    distribution = {str(h): round(c / total, 3) for h, c in sorted(hour_counts.items())}

    # Peak hours: hours with >10% of messages
    peak_hours = sorted([h for h, c in hour_counts.items() if c / total > 0.1])

    return {
        "value": {"peak_hours": peak_hours, "distribution": distribution},
        "sample_size": total,
    }


async def compute_engagement_by_category(user_id: str) -> dict:
    """Compute per-category engagement rates from ProactiveFeedback."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

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
        return {"value": {}, "sample_size": 0}

    category_stats: dict[str, dict] = {}
    for e in entries:
        cat = e.category or "unknown"
        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "engaged": 0}
        category_stats[cat]["total"] += 1
        if e.outcome in _ENGAGED_OUTCOMES:
            category_stats[cat]["engaged"] += 1

    rates = {
        cat: round(s["engaged"] / s["total"], 3) if s["total"] else 0.0
        for cat, s in category_stats.items()
    }

    return {"value": rates, "sample_size": len(entries)}


async def compute_response_speed(user_id: str) -> dict:
    """Compute response speed stats from ProactiveFeedback latencies."""
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
        return {"value": {"avg": None, "median": None, "fast_pct": 0.0}, "sample_size": 0}

    sorted_lat = sorted(latencies)
    avg = round(sum(sorted_lat) / len(sorted_lat), 1)
    median = sorted_lat[len(sorted_lat) // 2]
    fast_pct = round(sum(1 for lat in sorted_lat if lat < 300) / len(sorted_lat), 3)  # < 5 min

    return {
        "value": {"avg": avg, "median": median, "fast_pct": fast_pct},
        "sample_size": len(sorted_lat),
    }


async def compute_message_length_pref(user_id: str) -> dict:
    """Compute preferred message length from user's ChatMessage word counts."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    async with async_session() as session:
        result = await session.execute(
            select(ChatMessage.content)
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= cutoff,
            )
        )
        messages = [row[0] for row in result.all() if row[0]]

    if not messages:
        return {"value": {"preference": "unknown", "avg_words": 0}, "sample_size": 0}

    word_counts = [len(m.split()) for m in messages]
    avg_words = round(sum(word_counts) / len(word_counts), 1)

    if avg_words < 5:
        pref = "short"
    elif avg_words < 20:
        pref = "medium"
    else:
        pref = "long"

    return {"value": {"preference": pref, "avg_words": avg_words}, "sample_size": len(messages)}


async def compute_signal_sensitivity(user_id: str) -> dict:
    """Compute which signal types the user engages with vs ignores."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

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

    if not entries:
        return {"value": {"sensitive_to": [], "ignores": []}, "sample_size": 0}

    signal_stats: dict[str, dict] = {}
    for e in entries:
        triggers = e.trigger_signals or []
        for sig in triggers:
            if sig not in signal_stats:
                signal_stats[sig] = {"total": 0, "engaged": 0}
            signal_stats[sig]["total"] += 1
            if e.outcome in _ENGAGED_OUTCOMES:
                signal_stats[sig]["engaged"] += 1

    sensitive_to = []
    ignores = []
    for sig, stats in signal_stats.items():
        if stats["total"] < 2:
            continue
        rate = stats["engaged"] / stats["total"]
        if rate >= 0.6:
            sensitive_to.append(sig)
        elif rate <= 0.2:
            ignores.append(sig)

    return {
        "value": {"sensitive_to": sensitive_to, "ignores": ignores},
        "sample_size": len(entries),
    }


async def compute_language_register(user_id: str) -> dict:
    """Compute user's language register from message formality markers.

    Analyzes punctuation, capitalization, avg word length, and slang frequency
    to classify the user's typical writing style.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    async with async_session() as session:
        result = await session.execute(
            select(ChatMessage.content)
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= cutoff,
            )
        )
        messages = [row[0] for row in result.all() if row[0] and len(row[0].strip()) > 0]

    if not messages:
        return {"value": {"level": "casual", "markers": {}}, "sample_size": 0}

    total = len(messages)

    # Formality markers
    has_period = sum(1 for m in messages if m.rstrip().endswith("."))
    has_caps = sum(1 for m in messages if m[0].isupper())
    has_punctuation = sum(1 for m in messages if any(c in m for c in ".,;:!?"))

    # Casual markers
    casual_markers = {"lol", "haha", "ya", "ok", "k", "lmao", "bruh", "nah", "yep", "nope",
                      "omg", "idk", "tbh", "imo", "btw", "smth", "sth", "rn", "ngl"}
    singlish_markers = {"la", "lah", "lor", "leh", "sia", "hor", "meh", "ah", "can", "bo",
                        "sian", "wah", "eh", "aiyo", "walao", "paiseh"}

    casual_count = 0
    singlish_count = 0
    for m in messages:
        words = set(m.lower().split())
        if words & casual_markers:
            casual_count += 1
        if words & singlish_markers:
            singlish_count += 1

    # Avg word length (longer words tend to be more formal)
    all_words = " ".join(messages).split()
    avg_word_len = round(sum(len(w) for w in all_words) / len(all_words), 1) if all_words else 0

    # Score: higher = more formal
    formality_score = 0
    formality_score += (has_period / total) * 2
    formality_score += (has_caps / total) * 1.5
    formality_score += (has_punctuation / total) * 1
    formality_score -= (casual_count / total) * 2
    formality_score -= (singlish_count / total) * 1.5
    if avg_word_len > 5:
        formality_score += 1

    if formality_score >= 3:
        level = "formal"
    elif formality_score >= 1:
        level = "casual"
    else:
        level = "very_casual"

    markers = {
        "period_rate": round(has_period / total, 2),
        "caps_rate": round(has_caps / total, 2),
        "casual_marker_rate": round(casual_count / total, 2),
        "singlish_marker_rate": round(singlish_count / total, 2),
        "avg_word_length": avg_word_len,
        "formality_score": round(formality_score, 2),
    }

    return {"value": {"level": level, "markers": markers}, "sample_size": total}


# Registry: behavior_key → computation function
BEHAVIOR_COMPUTERS: dict[str, callable] = {
    "active_hours": compute_active_hours,
    "engagement_by_category": compute_engagement_by_category,
    "response_speed": compute_response_speed,
    "message_length_pref": compute_message_length_pref,
    "signal_sensitivity": compute_signal_sensitivity,
    "language_register": compute_language_register,
}

# Feedback-derived metrics (computed from ProactiveFeedback, also nightly)
# Imported from feedback_metrics and merged so reflection runs them all.
try:
    from donna.brain.feedback_metrics import FEEDBACK_COMPUTERS
    BEHAVIOR_COMPUTERS.update(FEEDBACK_COMPUTERS)
except ImportError:
    pass  # feedback_metrics not yet available
