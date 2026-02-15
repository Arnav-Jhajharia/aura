import logging
from datetime import datetime, timedelta

from tools.composio_client import execute_tool

logger = logging.getLogger(__name__)


async def get_calendar_events(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Get calendar events for a given date range via Composio."""
    date_str = kwargs.get("date", "today")
    days = kwargs.get("days", 1)

    if date_str == "today":
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_str == "tomorrow":
        start = (datetime.utcnow() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        try:
            start = datetime.fromisoformat(date_str)
        except ValueError:
            start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    end = start + timedelta(days=days)

    result = await execute_tool(
        slug="GOOGLECALENDAR_FIND_EVENT",
        user_id=user_id,
        arguments={
            "calendar_id": "primary",
            "time_min": start.isoformat() + "Z",
            "time_max": end.isoformat() + "Z",
            "single_events": True,
            "order_by": "startTime",
            "max_results": 20,
        },
    )

    if not result.get("successful"):
        error = str(result.get("error", "Unknown error"))
        if "not connected" in error.lower() or "no connected account" in error.lower():
            return [{"error": "Google Calendar not connected."}]
        return [{"error": f"Calendar API error: {error}"}]

    data = result.get("data", {})
    items = data.get("items", data) if isinstance(data, dict) else data

    if not isinstance(items, list):
        items = [items] if items else []

    return [
        {
            "title": item.get("summary", ""),
            "start": (
                item.get("start", {}).get("dateTime", item.get("start", {}).get("date", ""))
                if isinstance(item.get("start"), dict)
                else item.get("start", "")
            ),
            "end": (
                item.get("end", {}).get("dateTime", item.get("end", {}).get("date", ""))
                if isinstance(item.get("end"), dict)
                else item.get("end", "")
            ),
            "location": item.get("location", ""),
        }
        for item in items
    ]


async def create_calendar_event(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Create a new Google Calendar event via Composio."""
    title = kwargs.get("title", "New Event")
    start = kwargs.get("start", "")
    end = kwargs.get("end", "")
    description = kwargs.get("description", "")

    result = await execute_tool(
        slug="GOOGLECALENDAR_CREATE_EVENT",
        user_id=user_id,
        arguments={
            "calendar_id": "primary",
            "summary": title,
            "description": description,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
        },
    )

    if not result.get("successful"):
        error = str(result.get("error", "Unknown error"))
        if "not connected" in error.lower() or "no connected account" in error.lower():
            return {"error": "Google Calendar not connected."}
        return {"error": f"Failed to create event: {error}"}

    data = result.get("data", {})
    return {
        "success": True,
        "event_id": data.get("id", ""),
        "link": data.get("htmlLink", ""),
    }


async def find_free_slots(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Find free time slots in the user's calendar for a given day."""
    date_str = kwargs.get("date", "today")

    if date_str == "today":
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_str == "tomorrow":
        start = (datetime.utcnow() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        try:
            start = datetime.fromisoformat(date_str)
        except ValueError:
            start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    end = start + timedelta(days=1)

    # Try Composio's native free-slots action first
    result = await execute_tool(
        slug="GOOGLECALENDAR_FIND_FREE_SLOTS",
        user_id=user_id,
        arguments={
            "calendar_id": "primary",
            "time_min": start.isoformat() + "Z",
            "time_max": end.isoformat() + "Z",
        },
    )

    if result.get("successful"):
        data = result.get("data", {})
        slots = data.get("free_slots", data) if isinstance(data, dict) else data
        if isinstance(slots, list) and slots:
            return slots

    # Fall back to local gap-finding algorithm
    events = await get_calendar_events(user_id, **kwargs)
    if events and isinstance(events[0], dict) and "error" in events[0]:
        return events

    min_duration = kwargs.get("min_duration_minutes", 60)

    occupied = []
    for event in events:
        try:
            s = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(event["end"].replace("Z", "+00:00"))
            occupied.append((s, e))
        except (ValueError, KeyError):
            continue

    occupied.sort(key=lambda x: x[0])

    day_start = datetime.utcnow().replace(hour=8, minute=0, second=0, microsecond=0)
    day_end = day_start.replace(hour=22)

    free_slots = []
    current = day_start

    for s, e in occupied:
        if current < s:
            gap_minutes = (s - current).total_seconds() / 60
            if gap_minutes >= min_duration:
                free_slots.append({
                    "start": current.isoformat(),
                    "end": s.isoformat(),
                    "duration_minutes": int(gap_minutes),
                })
        current = max(current, e)

    if current < day_end:
        gap_minutes = (day_end - current).total_seconds() / 60
        if gap_minutes >= min_duration:
            free_slots.append({
                "start": current.isoformat(),
                "end": day_end.isoformat(),
                "duration_minutes": int(gap_minutes),
            })

    return free_slots
