import json
import logging
from zoneinfo import available_timezones

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import select

from agent.state import AuraState
from config import settings
from db.models import User
from db.session import async_session
from tools.whatsapp import send_whatsapp_buttons, send_whatsapp_message

logger = logging.getLogger(__name__)

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)

TIMEZONE_PARSE_PROMPT = """The user is telling you their timezone or location. Return ONLY the IANA timezone string (e.g. "Asia/Singapore", "America/New_York", "Europe/London"). If unclear, default to "UTC". Return nothing else."""

TIME_PARSE_PROMPT = """The user is describing when their day starts and ends. Extract wake_time and sleep_time as "HH:MM" in 24-hour format.
Return JSON only: {"wake_time": "HH:MM", "sleep_time": "HH:MM"}
If only one time is mentioned, use 08:00 for wake and 23:00 for sleep as defaults."""


async def _save_step(user_id: str, **kwargs) -> None:
    """Persist onboarding_step and any other fields to the User row."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        for k, v in kwargs.items():
            setattr(user, k, v)
        await session.commit()


async def onboarding_handler(state: AuraState) -> dict:
    """Drive the new-user onboarding conversation.

    Step is loaded from DB via message_ingress (User.onboarding_step),
    so it persists even without the LangGraph checkpointer.

      None              → welcome + ask name
      awaiting_name     → save name, ask timezone
      awaiting_timezone → save timezone, ask schedule
      awaiting_schedule → save schedule, mark complete, send connect buttons
    """
    user_id = state["user_id"]
    phone = state["phone"]
    step = state.get("onboarding_step")
    user_input = (state.get("transcription") or state.get("raw_input", "")).strip()

    # ── Fresh user ────────────────────────────────────────────────────────────
    if step is None:
        await _save_step(user_id, onboarding_step="awaiting_name")
        return {
            "onboarding_step": "awaiting_name",
            "response": "Hi. I'm Donna.\n\nWhat's your name?",
        }

    # ── Got name ──────────────────────────────────────────────────────────────
    if step == "awaiting_name":
        name = user_input.split()[0].capitalize() if user_input else "there"
        await _save_step(user_id, name=name, onboarding_step="awaiting_timezone")
        return {
            "onboarding_step": "awaiting_timezone",
            "response": f"{name}. Where are you based?",
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
        # Show a short, readable label (e.g. "SGT" for Asia/Singapore)
        tz_label = timezone.split("/")[-1].replace("_", " ")
        return {
            "onboarding_step": "awaiting_schedule",
            "response": f"{tz_label}. When do you start and end your day? (e.g. 7am–midnight)",
        }

    # ── Got schedule → done ───────────────────────────────────────────────────
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

        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()
            user.wake_time = wake_time
            user.sleep_time = sleep_time
            user.onboarding_complete = True
            user.onboarding_step = "complete"
            name = user.name or "you"
            await session.commit()

        # Send completion text + interactive buttons (bypassing memory_writer's send)
        await send_whatsapp_message(
            to=phone,
            text=f"Done, {name}. Tasks, mood, expenses, memory — ready.",
        )
        # Canvas → PAT flow (reply button triggers token_collector)
        await send_whatsapp_buttons(
            to=phone,
            body="Connect your accounts to unlock everything.",
            buttons=[
                {"id": "connect_canvas", "title": "Connect Canvas"},
                {"id": "connect_google", "title": "Connect Google"},
                {"id": "connect_microsoft", "title": "Connect Outlook"},
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
