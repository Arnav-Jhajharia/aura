import json
import logging
import re
from zoneinfo import available_timezones

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import select

from agent.state import AuraState
from config import settings
from db.models import User
from db.session import async_session
from tools.whatsapp import send_whatsapp_buttons

logger = logging.getLogger(__name__)


# Country calling code → default IANA timezone.
# Only single-timezone countries (or the dominant timezone for that calling code).
# Multi-timezone countries (US +1, Russia +7, Australia +61, etc.) are omitted —
# we'll still ask those users.
_PHONE_TZ: dict[str, str] = {
    "65": "Asia/Singapore",
    "91": "Asia/Kolkata",
    "44": "Europe/London",
    "49": "Europe/Berlin",
    "33": "Europe/Paris",
    "81": "Asia/Tokyo",
    "82": "Asia/Seoul",
    "86": "Asia/Shanghai",
    "852": "Asia/Hong_Kong",
    "853": "Asia/Macau",
    "886": "Asia/Taipei",
    "66": "Asia/Bangkok",
    "60": "Asia/Kuala_Lumpur",
    "62": "Asia/Jakarta",
    "63": "Asia/Manila",
    "84": "Asia/Ho_Chi_Minh",
    "971": "Asia/Dubai",
    "966": "Asia/Riyadh",
    "974": "Asia/Qatar",
    "968": "Asia/Muscat",
    "973": "Asia/Bahrain",
    "965": "Asia/Kuwait",
    "972": "Asia/Jerusalem",
    "353": "Europe/Dublin",
    "31": "Europe/Amsterdam",
    "46": "Europe/Stockholm",
    "47": "Europe/Oslo",
    "45": "Europe/Copenhagen",
    "358": "Europe/Helsinki",
    "41": "Europe/Zurich",
    "43": "Europe/Vienna",
    "34": "Europe/Madrid",
    "39": "Europe/Rome",
    "30": "Europe/Athens",
    "48": "Europe/Warsaw",
    "32": "Europe/Brussels",
    "351": "Europe/Lisbon",
    "64": "Pacific/Auckland",
    "94": "Asia/Colombo",
    "880": "Asia/Dhaka",
    "977": "Asia/Kathmandu",
    "92": "Asia/Karachi",
    "234": "Africa/Lagos",
    "254": "Africa/Nairobi",
    "27": "Africa/Johannesburg",
    "20": "Africa/Cairo",
}


def _timezone_from_phone(phone: str) -> str | None:
    """Infer IANA timezone from a phone number's country calling code.

    Returns None for multi-timezone countries or unrecognized codes.
    """
    # Try 3-digit, then 2-digit, then 1-digit prefix
    for length in (3, 2, 1):
        prefix = phone[:length]
        if prefix in _PHONE_TZ:
            return _PHONE_TZ[prefix]
    return None


def _looks_like_name(text: str | None) -> str | None:
    """Return a cleaned first name if the text looks like a real person's name, else None.

    Rejects phone numbers, empty strings, single chars, and common non-name patterns.
    """
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    # Reject if it's mostly digits (phone number / ID)
    if sum(c.isdigit() for c in cleaned) > len(cleaned) * 0.3:
        return None
    # Reject single character
    if len(cleaned) < 2:
        return None
    # Must contain at least one letter
    if not re.search(r"[a-zA-Z]", cleaned):
        return None
    # Take the first word as the first name
    first = cleaned.split()[0]
    # Reject if it's a single character after splitting
    if len(first) < 2:
        return None
    return first.capitalize()

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)

TIMEZONE_PARSE_PROMPT = """The user is telling you their timezone or location. Return ONLY the IANA timezone string (e.g. "Asia/Singapore", "America/New_York", "Europe/London"). If unclear, default to "UTC". Return nothing else."""

TIME_PARSE_PROMPT = """The user is describing when their day starts and ends. Extract wake_time and sleep_time as "HH:MM" in 24-hour format.
Return JSON only: {"wake_time": "HH:MM", "sleep_time": "HH:MM"}
If only one time is mentioned, use 08:00 for wake and 23:00 for sleep as defaults."""

YEAR_MAJOR_PROMPT = """The user is telling you their year of study and/or major/faculty. Extract what you can.
Return JSON only: {"academic_year": <int or null>, "faculty": "<string or null>", "major": "<string or null>"}
Examples:
- "year 2 CS" → {"academic_year": 2, "faculty": "Computing", "major": "Computer Science"}
- "y3 biz" → {"academic_year": 3, "faculty": "Business", "major": null}
- "freshie" → {"academic_year": 1, "faculty": null, "major": null}
If nothing can be extracted, return {"academic_year": null, "faculty": null, "major": null}."""


async def _save_step(user_id: str, **kwargs) -> None:
    """Persist onboarding_step and any other fields to the User row."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            logger.error("_save_step: user %s not found", user_id)
            return
        for k, v in kwargs.items():
            setattr(user, k, v)
        await session.commit()


async def onboarding_handler(state: AuraState) -> dict:
    """Drive the new-user onboarding conversation.

    Donna's first impression — confident, warm, never robotic. Each step has
    personality and gives the user a reason why she's asking.

    Step flow (persisted in User.onboarding_step):
      None                → welcome + ask name (or skip if WA profile name available)
      awaiting_name       → save name, confirm timezone or ask it
      awaiting_tz_confirm → confirm detected timezone (buttons: Yes / Somewhere else)
      awaiting_timezone   → save timezone, ask schedule
      awaiting_schedule   → save schedule, ask year/major
      awaiting_year_major → save academic info, complete onboarding
    """
    user_id = state["user_id"]
    phone = state["phone"]
    step = state.get("onboarding_step")
    user_input = (state.get("transcription") or state.get("raw_input", "")).strip()

    # ── Fresh user ────────────────────────────────────────────────────────────
    if step is None:
        wa_name = _looks_like_name(state.get("wa_profile_name"))
        detected_tz = _timezone_from_phone(phone)

        if wa_name and detected_tz:
            # Have both name and detected timezone — confirm with buttons
            tz_label = detected_tz.split("/")[-1].replace("_", " ")
            await _save_step(
                user_id, name=wa_name, timezone=detected_tz,
                onboarding_step="awaiting_tz_confirm",
            )
            await send_whatsapp_buttons(
                to=phone,
                body=(
                    f"Hi {wa_name}. I'm Donna.\n\n"
                    "I handle your schedule, deadlines, expenses, "
                    "mood — all of it. You just talk to me like a normal person.\n\n"
                    f"I've got you in {tz_label} — right?"
                ),
                buttons=[
                    {"id": "tz_confirm_yes", "title": "Yes"},
                    {"id": "tz_confirm_other", "title": "Somewhere else"},
                ],
            )
            return {
                "onboarding_step": "awaiting_tz_confirm",
                "response": None,
            }

        if wa_name:
            # Have name but can't determine timezone — skip name, ask timezone
            await _save_step(user_id, name=wa_name, onboarding_step="awaiting_timezone")
            return {
                "onboarding_step": "awaiting_timezone",
                "response": (
                    f"Hi {wa_name}. I'm Donna.\n\n"
                    "I handle your schedule, deadlines, expenses, "
                    "mood — all of it. You just talk to me like a normal person.\n\n"
                    "Where are you based? I need your timezone so I don't wake you up at 3am."
                ),
            }

        # No usable name from WhatsApp — ask for it
        await _save_step(user_id, onboarding_step="awaiting_name")
        return {
            "onboarding_step": "awaiting_name",
            "response": (
                "Today's your lucky day.\n\n"
                "I'm Donna. I handle your schedule, deadlines, expenses, "
                "mood — all of it. You just talk to me like a normal person.\n\n"
                "First things first. What's your name?"
            ),
        }

    # ── Got name ──────────────────────────────────────────────────────────────
    if step == "awaiting_name":
        name = user_input.split()[0].capitalize() if user_input else "there"
        detected_tz = _timezone_from_phone(phone)

        if detected_tz:
            # Know timezone from phone — confirm with buttons
            tz_label = detected_tz.split("/")[-1].replace("_", " ")
            await _save_step(
                user_id, name=name, timezone=detected_tz,
                onboarding_step="awaiting_tz_confirm",
            )
            await send_whatsapp_buttons(
                to=phone,
                body=(
                    f"{name}. Good.\n\n"
                    f"I've got you in {tz_label} — right?"
                ),
                buttons=[
                    {"id": "tz_confirm_yes", "title": "Yes"},
                    {"id": "tz_confirm_other", "title": "Somewhere else"},
                ],
            )
            return {
                "onboarding_step": "awaiting_tz_confirm",
                "response": None,
            }

        await _save_step(user_id, name=name, onboarding_step="awaiting_timezone")
        return {
            "onboarding_step": "awaiting_timezone",
            "response": (
                f"{name}. Good.\n\n"
                "Where are you based? I need your timezone so I don't wake you up at 3am."
            ),
        }

    # ── Timezone confirmation (button response) ────────────────────────────────
    if step == "awaiting_tz_confirm":
        raw_lower = user_input.lower().strip()
        if raw_lower in ("tz_confirm_yes", "yes", "yep", "yeah", "correct", "right"):
            # Timezone already saved from detection — proceed to schedule
            await _save_step(user_id, onboarding_step="awaiting_schedule")
            return {
                "onboarding_step": "awaiting_schedule",
                "response": (
                    "Good.\n\n"
                    "When does your day start and end? "
                    "I'll only message you inside that window.\n\n"
                    "e.g. \"8am to midnight\""
                ),
            }
        if raw_lower == "tz_confirm_other":
            # Wrong guess — ask explicitly
            await _save_step(user_id, timezone=None, onboarding_step="awaiting_timezone")
            return {
                "onboarding_step": "awaiting_timezone",
                "response": "No problem. Where are you based?",
            }
        # User might have typed their actual location directly
        tz_reply = await llm.ainvoke([
            SystemMessage(content=TIMEZONE_PARSE_PROMPT),
            HumanMessage(content=user_input),
        ])
        timezone = tz_reply.content.strip()
        if timezone in available_timezones():
            await _save_step(user_id, timezone=timezone, onboarding_step="awaiting_schedule")
            tz_label = timezone.split("/")[-1].replace("_", " ")
            return {
                "onboarding_step": "awaiting_schedule",
                "response": (
                    f"{tz_label}. Got it.\n\n"
                    "When does your day start and end? "
                    "I'll only message you inside that window.\n\n"
                    "e.g. \"8am to midnight\""
                ),
            }
        # Couldn't parse — ask explicitly
        await _save_step(user_id, timezone=None, onboarding_step="awaiting_timezone")
        return {
            "onboarding_step": "awaiting_timezone",
            "response": "Didn't catch that. Where are you based? City or timezone works.",
        }

    # ── Got timezone ──────────────────────────────────────────────────────────
    if step == "awaiting_timezone":
        tz_reply = await llm.ainvoke([
            SystemMessage(content=TIMEZONE_PARSE_PROMPT),
            HumanMessage(content=user_input),
        ])
        timezone = tz_reply.content.strip()
        if timezone not in available_timezones():
            timezone = "UTC"
        await _save_step(user_id, timezone=timezone, onboarding_step="awaiting_schedule")
        tz_label = timezone.split("/")[-1].replace("_", " ")
        return {
            "onboarding_step": "awaiting_schedule",
            "response": (
                f"{tz_label}. Got it.\n\n"
                "When does your day start and end? "
                "I'll only message you inside that window.\n\n"
                "e.g. \"8am to midnight\""
            ),
        }

    # ── Got schedule → ask year/major ─────────────────────────────────────────
    if step == "awaiting_schedule":
        time_reply = await llm.ainvoke([
            SystemMessage(content=TIME_PARSE_PROMPT),
            HumanMessage(content=user_input),
        ])
        try:
            times = json.loads(time_reply.content)
            wake_time = times.get("wake_time", "08:00")
            sleep_time = times.get("sleep_time", "23:00")
        except Exception:
            wake_time, sleep_time = "08:00", "23:00"

        await _save_step(
            user_id, wake_time=wake_time, sleep_time=sleep_time,
            onboarding_step="awaiting_year_major",
        )
        return {
            "onboarding_step": "awaiting_year_major",
            "response": (
                "Noted. I'll respect that.\n\n"
                "What year and major? Helps me know which deadlines matter to you.\n\n"
                "e.g. \"Y2 CS\", \"year 3 biz\""
            ),
        }

    # ── Got year/major → done ──────────────────────────────────────────────────
    if step == "awaiting_year_major":
        try:
            ym_reply = await llm.ainvoke([
                SystemMessage(content=YEAR_MAJOR_PROMPT),
                HumanMessage(content=user_input),
            ])
            ym = json.loads(ym_reply.content)
        except Exception:
            ym = {}

        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                logger.error("onboarding year/major: user %s not found", user_id)
                return {"response": None}
            if ym.get("academic_year"):
                user.academic_year = ym["academic_year"]
            if ym.get("faculty"):
                user.faculty = ym["faculty"]
            if ym.get("major"):
                user.major = ym["major"]
            user.onboarding_complete = True
            user.onboarding_step = "complete"
            name = user.name or "you"
            await session.commit()

        # ── Completion: short and confident ───────────────────────────
        # Don't list features. Let the buttons do the talking.
        await send_whatsapp_buttons(
            to=phone,
            body=f"We're set, {name}. Connect your stuff and I get a lot better.",
            buttons=[
                {"id": "connect_canvas", "title": "Canvas"},
                {"id": "connect_google", "title": "Google"},
                {"id": "connect_microsoft", "title": "Outlook"},
            ],
        )

        # Give immediate actions — the user learns by doing, not reading.
        await send_whatsapp_buttons(
            to=phone,
            body="Or just try me.",
            buttons=[
                {"id": "starter_due", "title": "What's due?"},
                {"id": "starter_mood", "title": "Log my mood"},
                {"id": "starter_task", "title": "Add a task"},
            ],
        )

        updated_context = {**state.get("user_context", {}), "onboarding_complete": True}
        # response=None so memory_writer doesn't send a duplicate
        return {
            "onboarding_step": "complete",
            "user_context": updated_context,
            "response": None,
        }

    logger.warning("onboarding_handler reached unexpected step=%s for user %s", step, user_id)
    return {"response": None}
