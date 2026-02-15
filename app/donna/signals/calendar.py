"""Calendar signal collector — polls Google Calendar via Composio."""

import logging
from datetime import datetime, timedelta, timezone

from donna.signals.base import Signal, SignalType
from tools.calendar import get_calendar_events

logger = logging.getLogger(__name__)


async def collect_calendar_signals(user_id: str) -> list[Signal]:
    """Generate signals from the user's Google Calendar."""
    now = datetime.now(timezone.utc)
    signals: list[Signal] = []

    # Fetch today's events
    today_events = await get_calendar_events(
        user_id=user_id, date=now.strftime("%Y-%m-%dT00:00:00"), days=1,
    )

    # Bail if calendar not connected (returns error dict)
    if today_events and isinstance(today_events[0], dict) and "error" in today_events[0]:
        return []

    # ── Empty / busy day ─────────────────────────────────────────────────
    if not today_events:
        signals.append(Signal(
            type=SignalType.CALENDAR_EMPTY_DAY,
            user_id=user_id,
            data={"date": now.date().isoformat()},
        ))
    elif len(today_events) >= 5:
        signals.append(Signal(
            type=SignalType.CALENDAR_BUSY_DAY,
            user_id=user_id,
            data={"event_count": len(today_events), "date": now.date().isoformat()},
        ))

    # ── Approaching events (within next 60 min) ─────────────────────────
    for event in today_events:
        start_str = event.get("start", "")
        if not start_str:
            continue
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        minutes_away = (start_dt - now).total_seconds() / 60

        if 0 < minutes_away <= 60:
            signals.append(Signal(
                type=SignalType.CALENDAR_EVENT_APPROACHING,
                user_id=user_id,
                data={
                    "title": event.get("title", ""),
                    "start": start_str,
                    "minutes_away": round(minutes_away),
                    "location": event.get("location", ""),
                },
            ))
        elif -15 <= minutes_away <= 0:
            signals.append(Signal(
                type=SignalType.CALENDAR_EVENT_STARTED,
                user_id=user_id,
                data={
                    "title": event.get("title", ""),
                    "start": start_str,
                    "minutes_ago": round(abs(minutes_away)),
                },
            ))

    # ── Free time gaps (>= 2 hours in remaining day) ────────────────────
    remaining_events = []
    for event in today_events:
        start_str = event.get("start", "")
        end_str = event.get("end", "")
        if not start_str or not end_str:
            continue
        try:
            s = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            if e > now:  # only future/ongoing events
                remaining_events.append((s, e))
        except ValueError:
            continue

    remaining_events.sort(key=lambda x: x[0])

    # Find gaps between events
    cursor = now
    day_end = now.replace(hour=22, minute=0, second=0, microsecond=0)

    for s, e in remaining_events:
        if cursor < s:
            gap_hours = (s - cursor).total_seconds() / 3600
            if gap_hours >= 2:
                signals.append(Signal(
                    type=SignalType.CALENDAR_GAP_DETECTED,
                    user_id=user_id,
                    data={
                        "start": cursor.isoformat(),
                        "end": s.isoformat(),
                        "duration_hours": round(gap_hours, 1),
                    },
                ))
        cursor = max(cursor, e)

    # Gap after last event until end of day
    if cursor < day_end:
        gap_hours = (day_end - cursor).total_seconds() / 3600
        if gap_hours >= 2:
            signals.append(Signal(
                type=SignalType.CALENDAR_GAP_DETECTED,
                user_id=user_id,
                data={
                    "start": cursor.isoformat(),
                    "end": day_end.isoformat(),
                    "duration_hours": round(gap_hours, 1),
                },
            ))

    return signals
