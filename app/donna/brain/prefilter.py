"""Pre-filter — applies hard rules BEFORE the LLM call to skip wasted cycles."""

import logging
import zoneinfo
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ChatMessage, User, UserBehavior
from db.session import async_session
from donna.brain.rules import count_proactive_today
from donna.brain.trust import compute_trust_level
from donna.signals.base import Signal

logger = logging.getLogger(__name__)

COOLDOWN_MINUTES = 30
URGENT_SIGNAL_THRESHOLD = 8  # signal urgency_hint that bypasses hard rules


def _get_local_hour(user_tz: str) -> int:
    """Get current hour in the user's timezone."""
    try:
        tz = zoneinfo.ZoneInfo(user_tz)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        tz = timezone.utc
    return datetime.now(tz).hour


def _has_urgent_signal(signals: list[Signal], threshold: int = URGENT_SIGNAL_THRESHOLD) -> bool:
    return any(s.urgency_hint >= threshold for s in signals)


async def prefilter_signals(
    user_id: str,
    signals: list[Signal],
    user_tz: str = "UTC",
) -> tuple[list[Signal], bool, dict, str | None]:
    """Apply hard rules before LLM.

    Returns (filtered_signals, should_continue, trust_info, block_reason).
    block_reason is None when should_continue=True.
    """
    empty_trust: dict = {"level": "new", "days_active": 0, "total_interactions": 0,
                         "score_threshold": 7.0, "daily_cap": 2, "min_urgency": 7}

    if not signals:
        return [], False, empty_trust, "no_signals"

    # ── Compute trust level ────────────────────────────────────────────
    trust_info = await compute_trust_level(user_id)
    min_urgency = trust_info["min_urgency"]
    daily_cap = trust_info["daily_cap"]

    has_urgent = _has_urgent_signal(signals)

    # ── Load signal sensitivity from UserBehavior ──────────────────────
    ignored_signals: set[str] = set()
    try:
        async with async_session() as session:
            sens_result = await session.execute(
                select(UserBehavior.value).where(
                    UserBehavior.user_id == user_id,
                    UserBehavior.behavior_key == "signal_sensitivity",
                )
            )
            sens_row = sens_result.scalar_one_or_none()
            if sens_row and isinstance(sens_row, dict):
                ignored_signals = set(sens_row.get("ignores", []))
    except Exception:
        pass  # graceful — use empty set

    # ── Load category suppression from UserBehavior ───────────────────
    suppressed_categories: dict = {}
    try:
        async with async_session() as session:
            sup_result = await session.execute(
                select(UserBehavior.value).where(
                    UserBehavior.user_id == user_id,
                    UserBehavior.behavior_key == "category_suppression",
                )
            )
            sup_row = sup_result.scalar_one_or_none()
            if sup_row and isinstance(sup_row, dict):
                suppressed_categories = sup_row.get("suppressed", {})
    except Exception:
        pass  # graceful — use empty dict

    # ── Filter signals below trust min_urgency ─────────────────────────
    # If user ignores certain signal types, require +2 urgency for those
    filtered_signals = []
    for s in signals:
        effective_min = min_urgency
        if s.type.value in ignored_signals:
            effective_min = min_urgency + 2
        if s.urgency_hint >= effective_min:
            filtered_signals.append(s)
    if not filtered_signals and not has_urgent:
        logger.debug(
            "Prefilter: no signals meet min_urgency=%d for user %s (trust=%s)",
            min_urgency, user_id, trust_info["level"],
        )
        return [], False, trust_info, "low_urgency"

    # If urgent signals passed the has_urgent check but were in the original list,
    # make sure they're included
    if not filtered_signals and has_urgent:
        filtered_signals = [s for s in signals if s.urgency_hint >= URGENT_SIGNAL_THRESHOLD]

    # ── Fetch user profile ────────────────────────────────────────────
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if not user:
        logger.warning("Prefilter: user %s not found", user_id)
        return [], False, trust_info, "user_not_found"

    wake_time = user.wake_time or "08:00"
    sleep_time = user.sleep_time or "23:00"
    tz_name = user.timezone or user_tz

    # ── Quiet hours check ──────────────────────────────────────────────
    current_hour = _get_local_hour(tz_name)
    wake_hour = int(wake_time.split(":")[0])
    sleep_hour = int(sleep_time.split(":")[0])

    in_quiet_hours = False
    if sleep_hour > wake_hour:
        in_quiet_hours = current_hour >= sleep_hour or current_hour < wake_hour
    else:
        in_quiet_hours = sleep_hour <= current_hour < wake_hour

    if in_quiet_hours and not has_urgent:
        logger.debug("Prefilter: quiet hours for user %s — skipping", user_id)
        return [], False, trust_info, "quiet_hours"

    # ── Daily cap check (trust-dependent) ──────────────────────────────
    sent_today = await count_proactive_today(user_id)
    if sent_today >= daily_cap:
        logger.debug(
            "Prefilter: daily cap reached (%d/%d) for user %s",
            sent_today, daily_cap, user_id,
        )
        return [], False, trust_info, "daily_cap"

    # ── Cooldown check ─────────────────────────────────────────────────
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=COOLDOWN_MINUTES)
    async with async_session() as session:
        last_result = await session.execute(
            select(ChatMessage.created_at)
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "assistant",
                ChatMessage.is_proactive.is_(True),
                ChatMessage.created_at >= cutoff,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        recent_proactive = last_result.scalar_one_or_none()

    if recent_proactive is not None and not has_urgent:
        logger.debug("Prefilter: cooldown active for user %s", user_id)
        return [], False, trust_info, "cooldown"

    # Attach suppression data for downstream use
    if suppressed_categories:
        trust_info["suppressed_categories"] = suppressed_categories

    return filtered_signals, True, trust_info, None
