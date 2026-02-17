"""Signal deduplication — prevents the same signal from flooding Layer 2."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import SignalState, generate_uuid
from db.session import async_session
from donna.signals.base import Signal

logger = logging.getLogger(__name__)

# Per-type re-emit rules: how many hours must pass before the same signal is sent again.
_REEMIT_HOURS: dict[str, float] = {
    "calendar_event_approaching": 1,
    "calendar_event_started": 1,
    "calendar_gap_detected": 12,
    "calendar_busy_day": 24,
    "calendar_empty_day": 24,
    "canvas_deadline_approaching": 6,
    "canvas_overdue": 12,
    "canvas_grade_posted": 168,  # once per week
    "email_unread_piling": 6,
    "email_important_received": 24,
    "time_morning_window": 24,
    "time_evening_window": 24,
    "time_since_last_interaction": 6,
    "mood_trend_down": 24,
    "mood_trend_up": 24,
    "task_overdue": 12,
    "task_due_today": 12,
    "memory_relevance_window": 24,
    "habit_streak_at_risk": 12,
    "habit_streak_milestone": 168,
}

_DEFAULT_REEMIT_HOURS = 12


def _should_reemit(signal: Signal, state: SignalState) -> bool:
    """Return True if enough time has passed to re-emit this signal."""
    reemit_hours = _REEMIT_HOURS.get(signal.type.value, _DEFAULT_REEMIT_HOURS)
    threshold = state.last_seen + timedelta(hours=reemit_hours)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now >= threshold


async def deduplicate_signals(user_id: str, signals: list[Signal]) -> list[Signal]:
    """Filter out signals that have already been seen recently.

    For each signal:
    - Compute its dedup key
    - Look up existing state in the DB
    - If new → emit and create state
    - If seen recently → suppress
    - If enough time has passed → re-emit and update state
    """
    if not signals:
        return []

    # Compute dedup keys for all signals
    for sig in signals:
        sig.compute_dedup_key()

    dedup_keys = [sig.dedup_key for sig in signals]

    async with async_session() as session:
        # Fetch all existing states for this user in one query
        result = await session.execute(
            select(SignalState).where(
                SignalState.user_id == user_id,
                SignalState.dedup_key.in_(dedup_keys),
            )
        )
        existing_states = {state.dedup_key: state for state in result.scalars().all()}

        emitted: list[Signal] = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for sig in signals:
            state = existing_states.get(sig.dedup_key)

            if state is None:
                # New signal — emit and create state
                session.add(SignalState(
                    id=generate_uuid(),
                    user_id=user_id,
                    dedup_key=sig.dedup_key,
                    signal_type=sig.type.value,
                    first_seen=now,
                    last_seen=now,
                    times_seen=1,
                ))
                emitted.append(sig)
            else:
                # Update tracking regardless
                state.last_seen = now
                state.times_seen += 1

                if _should_reemit(sig, state):
                    emitted.append(sig)

        await session.commit()

    logger.info(
        "Dedup: %d/%d signals passed for user %s",
        len(emitted), len(signals), user_id,
    )
    return emitted
