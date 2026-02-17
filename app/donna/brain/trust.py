"""Trust ramp — computes how much proactive behavior a user should receive."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func

from db.models import ChatMessage, User
from db.session import async_session

logger = logging.getLogger(__name__)

# Trust level definitions
TRUST_LEVELS = {
    "new": {"score_threshold": 7.0, "daily_cap": 2, "min_urgency": 7},
    "building": {"score_threshold": 6.0, "daily_cap": 3, "min_urgency": 6},
    "established": {"score_threshold": 5.5, "daily_cap": 4, "min_urgency": 5},
    "deep": {"score_threshold": 5.0, "daily_cap": 5, "min_urgency": 4},
}


async def compute_trust_level(user_id: str) -> dict:
    """Return trust info: {"level", "days_active", "total_interactions", ...config}.

    Levels:
    - new: < 14 days OR < 20 user messages
    - building: < 30 days OR < 100 user messages
    - established: < 90 days
    - deep: >= 90 days
    """
    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        if not user or not user.created_at:
            return {"level": "new", "days_active": 0, "total_interactions": 0, **TRUST_LEVELS["new"]}

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        days_active = (now - user.created_at).days

        msg_result = await session.execute(
            select(func.count(ChatMessage.id))
            .where(ChatMessage.user_id == user_id, ChatMessage.role == "user")
        )
        total_interactions = msg_result.scalar_one()

    # Determine level
    if days_active < 14 or total_interactions < 20:
        level = "new"
    elif days_active < 30 or total_interactions < 100:
        level = "building"
    elif days_active < 90:
        level = "established"
    else:
        level = "deep"

    # ── Inactivity de-escalation ──────────────────────────────────
    level_order = ["new", "building", "established", "deep"]
    if user.last_active_at:
        inactive_days = (now - user.last_active_at).days
        if inactive_days >= 60:
            demote_steps = 2
        elif inactive_days >= 30:
            demote_steps = 1
        else:
            demote_steps = 0

        if demote_steps > 0:
            current_idx = level_order.index(level)
            new_idx = max(0, current_idx - demote_steps)
            if new_idx != current_idx:
                old_level = level
                level = level_order[new_idx]
                logger.info(
                    "Trust de-escalation for user %s: %s → %s (inactive %d days)",
                    user_id, old_level, level, inactive_days,
                )

    config = TRUST_LEVELS[level]
    return {
        "level": level,
        "days_active": days_active,
        "total_interactions": total_interactions,
        **config,
    }
