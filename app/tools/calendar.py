import logging
from datetime import datetime, timedelta, timezone

from tools.composio_client import execute_tool, get_email_provider

logger = logging.getLogger(__name__)


def _to_rfc3339(dt: datetime) -> str:
    """Convert a datetime to RFC3339 UTC string for Google Calendar API."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_date_range(date_str: str, days: int) -> tuple[datetime, datetime]:
    """Parse a date string + day count into (start, end) UTC datetimes."""
    if date_str == "today":
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_str == "tomorrow":
        start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        try:
            start = datetime.fromisoformat(date_str)
        except ValueError:
            start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=days)


def _normalize_events(items: list, provider: str) -> list[dict]:
    """Normalize calendar events from either provider to a common format."""
    normalized = []
    for item in items:
        if provider == "microsoft":
            start = item.get("start", {})
            end = item.get("end", {})
            normalized.append({
                "title": item.get("subject", ""),
                "start": start.get("dateTime", "") if isinstance(start, dict) else start,
                "end": end.get("dateTime", "") if isinstance(end, dict) else end,
                "location": (
                    item.get("location", {}).get("displayName", "")
                    if isinstance(item.get("location"), dict)
                    else item.get("location", "")
                ),
            })
        else:
            normalized.append({
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
            })
    return normalized


async def get_calendar_events(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Get calendar events for a given date range via Composio."""
    provider = await get_email_provider(user_id)
    if not provider:
        return [{"error": "Calendar not connected. Send /connect google or /connect microsoft to set up."}]

    date_str = kwargs.get("date", "today")
    days = kwargs.get("days", 1)
    start, end = _parse_date_range(date_str, days)

    if provider == "microsoft":
        result = await execute_tool(
            slug="OUTLOOK_GET_CALENDAR_VIEW",
            user_id=user_id,
            arguments={
                "start_date_time": _to_rfc3339(start),
                "end_date_time": _to_rfc3339(end),
            },
        )
    else:
        result = await execute_tool(
            slug="GOOGLECALENDAR_FIND_EVENT",
            user_id=user_id,
            arguments={
                "calendar_id": "primary",
                "time_min": _to_rfc3339(start),
                "time_max": _to_rfc3339(end),
                "single_events": True,
                "order_by": "startTime",
                "max_results": 20,
            },
        )

    if not result.get("successful"):
        error = str(result.get("error", "Unknown error"))
        if "not connected" in error.lower() or "no connected account" in error.lower():
            return [{"error": "Calendar not connected."}]
        return [{"error": f"Calendar API error: {error}"}]

    data = result.get("data", {})
    items = data.get("items", data.get("value", data)) if isinstance(data, dict) else data

    if not isinstance(items, list):
        items = [items] if items else []

    return _normalize_events(items, provider)


async def create_calendar_event(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Create a new calendar event via Composio (Google or Outlook)."""
    provider = await get_email_provider(user_id)
    if not provider:
        return {"error": "Calendar not connected."}

    title = kwargs.get("title", "New Event")
    start = kwargs.get("start", "")
    end = kwargs.get("end", "")
    description = kwargs.get("description", "")

    if provider == "microsoft":
        result = await execute_tool(
            slug="OUTLOOK_CALENDAR_CREATE_EVENT",
            user_id=user_id,
            arguments={
                "subject": title,
                "body": {"contentType": "text", "content": description},
                "start": {"dateTime": start, "timeZone": "UTC"},
                "end": {"dateTime": end, "timeZone": "UTC"},
            },
        )
    else:
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
            return {"error": "Calendar not connected."}
        return {"error": f"Failed to create event: {error}"}

    data = result.get("data", {})
    return {
        "success": True,
        "event_id": data.get("id", ""),
        "link": data.get("htmlLink", data.get("webLink", "")),
    }


async def find_free_slots(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Find free time slots in the user's calendar for a given day."""
    provider = await get_email_provider(user_id)
    if not provider:
        return [{"error": "Calendar not connected."}]

    date_str = kwargs.get("date", "today")
    start, end = _parse_date_range(date_str, 1)

    # Try provider-native free-slots action first
    if provider == "microsoft":
        result = await execute_tool(
            slug="OUTLOOK_FIND_MEETING_TIMES",
            user_id=user_id,
            arguments={
                "start_date_time": _to_rfc3339(start),
                "end_date_time": _to_rfc3339(end),
            },
        )
    else:
        result = await execute_tool(
            slug="GOOGLECALENDAR_FIND_FREE_SLOTS",
            user_id=user_id,
            arguments={
                "calendar_id": "primary",
                "time_min": _to_rfc3339(start),
                "time_max": _to_rfc3339(end),
            },
        )

    if result.get("successful"):
        data = result.get("data", {})
        slots = (
            data.get("free_slots", data.get("meetingTimeSuggestions", data))
            if isinstance(data, dict) else data
        )
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

    day_start = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
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


async def delete_calendar_event(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Delete a calendar event by event_id."""
    provider = await get_email_provider(user_id)
    if not provider:
        return {"error": "Calendar not connected."}

    event_id = kwargs.get("event_id", "")
    if not event_id:
        return {"error": "No event_id provided."}

    if provider == "microsoft":
        result = await execute_tool(
            slug="OUTLOOK_CALENDAR_DELETE_EVENT",
            user_id=user_id,
            arguments={"event_id": event_id},
        )
    else:
        result = await execute_tool(
            slug="GOOGLECALENDAR_DELETE_EVENT",
            user_id=user_id,
            arguments={"calendar_id": "primary", "event_id": event_id},
        )

    if not result.get("successful"):
        return {"error": f"Failed to delete event: {result.get('error', 'Unknown')}"}

    return {"success": True}


async def update_calendar_event(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Update an existing calendar event (title, time, description, location).

    Pass event_id and any fields to update: title, start, end, description, location.
    """
    provider = await get_email_provider(user_id)
    if not provider:
        return {"error": "Calendar not connected."}

    event_id = kwargs.get("event_id", "")
    if not event_id:
        return {"error": "No event_id provided."}

    title = kwargs.get("title")
    start = kwargs.get("start")
    end = kwargs.get("end")
    description = kwargs.get("description")
    location = kwargs.get("location")

    if provider == "microsoft":
        arguments = {"event_id": event_id}
        if title:
            arguments["subject"] = title
        if start:
            arguments["start"] = {"dateTime": start, "timeZone": "UTC"}
        if end:
            arguments["end"] = {"dateTime": end, "timeZone": "UTC"}
        if description:
            arguments["body"] = {"contentType": "text", "content": description}
        if location:
            arguments["location"] = {"displayName": location}
        result = await execute_tool(
            slug="OUTLOOK_CALENDAR_UPDATE_EVENT",
            user_id=user_id,
            arguments=arguments,
        )
    else:
        arguments = {"calendar_id": "primary", "event_id": event_id}
        if title:
            arguments["summary"] = title
        if start:
            arguments["start"] = {"dateTime": start, "timeZone": "UTC"}
        if end:
            arguments["end"] = {"dateTime": end, "timeZone": "UTC"}
        if description:
            arguments["description"] = description
        if location:
            arguments["location"] = location
        result = await execute_tool(
            slug="GOOGLECALENDAR_UPDATE_EVENT",
            user_id=user_id,
            arguments=arguments,
        )

    if not result.get("successful"):
        return {"error": f"Failed to update event: {result.get('error', 'Unknown')}"}

    return {"success": True}
