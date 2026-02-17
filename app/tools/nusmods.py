"""NUSMods timetable sync — fetches module data and creates Google Calendar events.

Parses a NUSMods share URL like:
    https://nusmods.com/timetable/sem-2/share?CS2103T=LEC:G17&CS1101S=LEC:1,TUT:05,REC:05

Fetches each module's timetable from the NUSMods API, matches the user's selected
lesson groups, computes actual dates from NUS week numbers, and creates recurring
Google Calendar events + exam events.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx

from tools.composio_client import execute_tool, get_email_provider

logger = logging.getLogger(__name__)

NUSMODS_API = "https://api.nusmods.com/v2"

# NUSMods URL short codes → API lessonType names
LESSON_TYPE_MAP = {
    "LEC": "Lecture",
    "TUT": "Tutorial",
    "REC": "Recitation",
    "LAB": "Laboratory",
    "SEC": "Sectional Teaching",
    "DLEC": "Design Lecture",
    "PLEC": "Packaged Lecture",
    "PTUT": "Packaged Tutorial",
    "SEM": "Seminar-Style Module Class",
    "WS": "Workshop",
    "MINI": "Mini-Project",
}

# Reverse map for display
LESSON_TYPE_SHORT = {v: k for k, v in LESSON_TYPE_MAP.items()}

DAY_OFFSET = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}

NUS_TZ = "Asia/Singapore"


# ── Date helpers ─────────────────────────────────────────────────

def _second_monday(year: int, month: int) -> date:
    """Return the second Monday of the given month (NUS semester start pattern)."""
    first = date(year, month, 1)
    dow = first.weekday()  # 0=Mon
    if dow == 0:
        first_monday = first
    else:
        first_monday = first + timedelta(days=(7 - dow))
    return first_monday + timedelta(weeks=1)


def _get_academic_year() -> str:
    """Determine current NUS academic year (e.g. '2025-2026')."""
    now = datetime.now(timezone.utc)
    # AY starts in August. If month >= 8, AY starts this year.
    start_year = now.year if now.month >= 8 else now.year - 1
    return f"{start_year}-{start_year + 1}"


def _get_semester_start(acad_year: str, semester: int) -> date:
    """Get the Monday of Week 1 for a given semester."""
    start_year, end_year = acad_year.split("-")
    if semester == 1:
        return _second_monday(int(start_year), 8)   # August
    elif semester == 2:
        return _second_monday(int(end_year), 1)      # January
    elif semester == 3:
        return _second_monday(int(end_year), 5)      # May (Special Term 1)
    elif semester == 4:
        return _second_monday(int(end_year), 6)      # June (Special Term 2)
    raise ValueError(f"Unknown semester: {semester}")


def _week_to_monday(sem_start: date, week_num: int) -> date:
    """Convert NUS week number to the Monday of that week.

    Accounts for the recess week between weeks 6 and 7.
    Weeks 1-6 are contiguous from sem_start.
    Weeks 7-13 are offset by +1 week (recess week gap).
    """
    if week_num <= 6:
        return sem_start + timedelta(weeks=week_num - 1)
    else:
        return sem_start + timedelta(weeks=week_num)  # +1 for recess


def _lesson_date(sem_start: date, week_num: int, day_name: str) -> date:
    """Get the actual calendar date for a lesson in a given NUS week + day."""
    monday = _week_to_monday(sem_start, week_num)
    return monday + timedelta(days=DAY_OFFSET.get(day_name, 0))


def _time_str_to_iso(d: date, time_str: str) -> str:
    """Convert a date + NUSMods time string ('0800') to ISO datetime in SGT."""
    hour = int(time_str[:2])
    minute = int(time_str[2:])
    return f"{d.isoformat()}T{hour:02d}:{minute:02d}:00"


# ── NUSMods API ──────────────────────────────────────────────────

async def _fetch_module(acad_year: str, module_code: str) -> dict | None:
    """Fetch module data from NUSMods API."""
    url = f"{NUSMODS_API}/{acad_year}/modules/{module_code}.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("NUSMods API returned %d for %s", resp.status_code, module_code)
            return None
    except Exception:
        logger.exception("Failed to fetch NUSMods data for %s", module_code)
        return None


# ── URL parsing ──────────────────────────────────────────────────

def _parse_nusmods_url(url: str) -> dict:
    """Parse NUSMods share URL into semester + module selections.

    Example: https://nusmods.com/timetable/sem-2/share?CS2103T=LEC:G17,TUT:08&CS2101=SEC:1
    Returns: {"semester": 2, "modules": [{"code": "CS2103T", "lessons": {"Lecture": "G17", "Tutorial": "08"}}, ...]}
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    sem_str = parts[1] if len(parts) >= 2 else "sem-1"
    semester = int(sem_str.split("-")[1])

    query = parse_qs(parsed.query)
    modules = []
    for code, values in query.items():
        lesson_str = values[0] if values else ""
        lessons = {}
        for part in lesson_str.split(","):
            if ":" not in part:
                continue
            short_type, class_no = part.split(":", 1)
            full_type = LESSON_TYPE_MAP.get(short_type.upper(), short_type)
            lessons[full_type] = class_no
        modules.append({"code": code, "lessons": lessons})

    return {"semester": semester, "modules": modules}


# ── Calendar event creation ──────────────────────────────────────

async def _create_calendar_event(
    user_id: str,
    summary: str,
    description: str,
    location: str,
    start_iso: str,
    end_iso: str,
    recurrence: list[str] | None = None,
) -> bool:
    """Create a calendar event via Composio (Google or Outlook)."""
    provider = await get_email_provider(user_id)

    if provider == "microsoft":
        arguments = {
            "subject": summary,
            "body": {"contentType": "text", "content": description},
            "location": {"displayName": location},
            "start": {"dateTime": start_iso, "timeZone": NUS_TZ},
            "end": {"dateTime": end_iso, "timeZone": NUS_TZ},
        }
        if recurrence:
            arguments["recurrence"] = recurrence
        slug = "OUTLOOK_CALENDAR_CREATE_EVENT"
    else:
        arguments = {
            "calendar_id": "primary",
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_iso, "timeZone": NUS_TZ},
            "end": {"dateTime": end_iso, "timeZone": NUS_TZ},
        }
        if recurrence:
            arguments["recurrence"] = recurrence
        slug = "GOOGLECALENDAR_CREATE_EVENT"

    result = await execute_tool(
        slug=slug,
        user_id=user_id,
        arguments=arguments,
    )

    if not result.get("successful"):
        logger.warning("Failed to create calendar event '%s': %s", summary, result.get("error"))
        return False
    return True


async def _create_lesson_events(
    user_id: str,
    module_code: str,
    module_title: str,
    lesson: dict,
    sem_start: date,
) -> int:
    """Create calendar events for a single lesson slot across all its weeks.

    Tries recurrence first. Falls back to individual events if recurrence fails.
    Returns the number of events created.
    """
    day_name = lesson["day"]
    start_time = lesson["startTime"]
    end_time = lesson["endTime"]
    venue = lesson.get("venue", "")
    lesson_type = lesson["lessonType"]
    class_no = lesson["classNo"]
    weeks = lesson.get("weeks", list(range(1, 14)))

    short_type = LESSON_TYPE_SHORT.get(lesson_type, lesson_type)
    summary = f"{module_code} {short_type}"
    description = (
        f"{module_code} — {module_title}\n"
        f"{lesson_type} Group {class_no}\n"
        f"📍 {venue}\n\n"
        f"[NUSMods sync]"
    )

    # Standard weeks (1-13): use weekly recurrence with EXDATE for recess
    standard_weeks = list(range(1, 14))
    if weeks == standard_weeks:
        first_date = _lesson_date(sem_start, 1, day_name)
        last_date = _lesson_date(sem_start, 13, day_name)
        # Recess week: the week after week 6 (sem_start + 6 weeks)
        recess_monday = sem_start + timedelta(weeks=6)
        recess_lesson_date = recess_monday + timedelta(days=DAY_OFFSET.get(day_name, 0))

        start_iso = _time_str_to_iso(first_date, start_time)
        end_iso = _time_str_to_iso(first_date, end_time)
        until = last_date.strftime("%Y%m%dT235959Z")
        exdate = f"{recess_lesson_date.strftime('%Y%m%d')}T{start_time[:2]}{start_time[2:]}00"

        recurrence = [
            f"RRULE:FREQ=WEEKLY;UNTIL={until}",
            f"EXDATE;TZID={NUS_TZ}:{exdate}",
        ]

        ok = await _create_calendar_event(
            user_id, summary, description, venue,
            start_iso, end_iso, recurrence=recurrence,
        )
        if ok:
            return 1

        # Recurrence failed — fall through to individual events
        logger.info("Recurrence failed for %s %s, falling back to individual events", module_code, lesson_type)

    # Non-standard weeks or recurrence fallback: create individual events
    created = 0
    sem = asyncio.Semaphore(5)  # limit concurrency

    async def _create_one(week: int) -> bool:
        async with sem:
            d = _lesson_date(sem_start, week, day_name)
            s = _time_str_to_iso(d, start_time)
            e = _time_str_to_iso(d, end_time)
            return await _create_calendar_event(
                user_id, summary, description, venue, s, e,
            )

    results = await asyncio.gather(*[_create_one(w) for w in weeks])
    created = sum(1 for r in results if r)
    return created


async def _create_exam_event(
    user_id: str,
    module_code: str,
    module_title: str,
    exam_date: str,
    exam_duration: int,
) -> bool:
    """Create a calendar event for an exam."""
    # exam_date is like "2026-05-04T01:00:00.000Z" (UTC)
    # Convert to SGT for display
    exam_dt = datetime.fromisoformat(exam_date.replace("Z", "+00:00"))
    import zoneinfo
    sgt = zoneinfo.ZoneInfo(NUS_TZ)
    exam_local = exam_dt.astimezone(sgt)
    end_local = exam_local + timedelta(minutes=exam_duration)

    summary = f"🚨 EXAM: {module_code}"
    description = (
        f"{module_code} — {module_title}\n"
        f"Duration: {exam_duration} minutes\n\n"
        f"[NUSMods sync]"
    )

    start_iso = exam_local.strftime("%Y-%m-%dT%H:%M:%S")
    end_iso = end_local.strftime("%Y-%m-%dT%H:%M:%S")

    return await _create_calendar_event(
        user_id, summary, description, "",
        start_iso, end_iso,
    )


# ── Main sync function ──────────────────────────────────────────

async def sync_nusmods_to_calendar(user_id: str, nusmods_url: str) -> dict:
    """Parse NUSMods URL, fetch timetable data, and create Google Calendar events.

    Returns a summary dict with counts and any errors.
    """
    parsed = _parse_nusmods_url(nusmods_url)
    semester = parsed["semester"]
    modules = parsed["modules"]
    acad_year = _get_academic_year()

    try:
        sem_start = _get_semester_start(acad_year, semester)
    except ValueError as e:
        return {"error": str(e), "events_created": 0, "exams_created": 0}

    logger.info(
        "NUSMods sync: AY %s Sem %d (week 1 = %s), %d module(s) for user %s",
        acad_year, semester, sem_start.isoformat(), len(modules), user_id,
    )

    events_created = 0
    exams_created = 0
    modules_synced = []
    errors = []

    for mod in modules:
        code = mod["code"]
        selected = mod["lessons"]  # {"Lecture": "G17", "Tutorial": "08"}

        module_data = await _fetch_module(acad_year, code)
        if not module_data:
            errors.append(f"{code}: module not found in NUSMods")
            continue

        module_title = module_data.get("title", code)
        sem_data = None
        for sd in module_data.get("semesterData", []):
            if sd["semester"] == semester:
                sem_data = sd
                break

        if not sem_data:
            errors.append(f"{code}: no data for semester {semester}")
            continue

        # Match and create lesson events
        for lesson_type, class_no in selected.items():
            matching = [
                les for les in sem_data.get("timetable", [])
                if les["lessonType"] == lesson_type and les["classNo"] == class_no
            ]

            if not matching:
                errors.append(f"{code}: {lesson_type} group {class_no} not found")
                continue

            for lesson in matching:
                count = await _create_lesson_events(
                    user_id, code, module_title, lesson, sem_start,
                )
                events_created += count
                logger.info(
                    "  %s %s %s %s %s-%s: %d event(s)",
                    code, lesson_type, class_no,
                    lesson["day"], lesson["startTime"], lesson["endTime"], count,
                )

        # Create exam event
        exam_date = sem_data.get("examDate")
        exam_duration = sem_data.get("examDuration", 120)
        if exam_date:
            ok = await _create_exam_event(
                user_id, code, module_title, exam_date, exam_duration,
            )
            if ok:
                exams_created += 1
                logger.info("  %s exam: %s (%dmin)", code, exam_date, exam_duration)
            else:
                errors.append(f"{code}: failed to create exam event")

        modules_synced.append(code)

    result = {
        "modules_synced": modules_synced,
        "events_created": events_created,
        "exams_created": exams_created,
        "semester": f"Sem {semester}",
        "academic_year": acad_year,
        "week1_start": sem_start.isoformat(),
    }
    if errors:
        result["errors"] = errors

    logger.info(
        "NUSMods sync done: %d events + %d exams for %d modules (%d errors)",
        events_created, exams_created, len(modules_synced), len(errors),
    )

    return result
