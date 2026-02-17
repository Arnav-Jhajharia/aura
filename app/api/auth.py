import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from config import settings
from db.models import User
from db.session import async_session
from tools.composio_client import initiate_connection
from tools.whatsapp import send_whatsapp_message

logger = logging.getLogger(__name__)
router = APIRouter()

# ── OAuth state management ───────────────────────────────────────────────
# Maps state token → {"user_id": str, "created_at": float}
# Tokens expire after 10 minutes. In-memory is fine for single-process;
# use Redis if scaling horizontally.
_oauth_states: dict[str, dict] = {}
_STATE_TTL_SECONDS = 600  # 10 minutes


def _create_state(user_id: str) -> str:
    """Generate a cryptographically random state token and store the mapping."""
    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"user_id": user_id, "created_at": time.time()}
    return state


def _verify_state(state: str | None) -> str:
    """Validate and consume a state token. Returns user_id or raises HTTPException."""
    if not state or state not in _oauth_states:
        raise HTTPException(status_code=403, detail="Invalid or expired OAuth state")

    entry = _oauth_states.pop(state)
    if time.time() - entry["created_at"] > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=403, detail="OAuth state expired")

    return entry["user_id"]


def _cleanup_expired_states() -> None:
    """Remove expired state tokens to prevent unbounded growth."""
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if now - v["created_at"] > _STATE_TTL_SECONDS]
    for k in expired:
        _oauth_states.pop(k, None)


# ---------- Google OAuth (via Composio) ----------
# Gmail and Google Calendar are separate Composio apps, each needing their own
# auth config. We chain them: Gmail first → callback initiates Calendar → done.


@router.get("/google/login")
async def google_login(user_id: str):
    """Start Google OAuth — initiate Gmail connection first."""
    state = _create_state(user_id)
    connection = await initiate_connection(
        user_id=user_id,
        auth_config_id=settings.composio_gmail_auth_config_id,
        config={"auth_scheme": "OAUTH2"},
        callback_url=f"{settings.api_base_url}/auth/google/callback/gmail?state={state}",
    )
    return RedirectResponse(connection.redirect_url)


@router.get("/google/callback/gmail")
async def google_callback_gmail(request: Request, state: str = ""):
    """Gmail OAuth done — now initiate Google Calendar connection."""
    user_id = _verify_state(state)
    logger.info("Gmail connected for user %s, chaining Calendar auth...", user_id)

    # New state for the calendar leg
    cal_state = _create_state(user_id)
    connection = await initiate_connection(
        user_id=user_id,
        auth_config_id=settings.composio_gcal_auth_config_id,
        config={"auth_scheme": "OAUTH2"},
        callback_url=f"{settings.api_base_url}/auth/google/callback/calendar?state={cal_state}",
    )
    return RedirectResponse(connection.redirect_url)


@router.get("/google/callback/calendar")
async def google_callback_calendar(request: Request, state: str = ""):
    """Both Gmail and Calendar are now connected. Confirm to the user."""
    user_id = _verify_state(state)

    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.has_google = True
            await session.commit()

    if user:
        await send_whatsapp_message(
            to=user.phone,
            text="Google connected. Calendar and Gmail are ready to go.",
        )

    logger.info("Google OAuth completed for user %s (Gmail + Calendar via Composio)", user_id)
    return HTMLResponse(
        "<h2>Google connected! You can close this tab and go back to WhatsApp.</h2>"
    )


# ---------- Microsoft Outlook (via Composio) ----------
# Microsoft Graph covers both mail + calendar in one OAuth consent — no chaining needed.


@router.get("/microsoft/login")
async def microsoft_login(user_id: str):
    """Start Microsoft OAuth — single step covers Outlook mail + calendar."""
    state = _create_state(user_id)
    connection = await initiate_connection(
        user_id=user_id,
        auth_config_id=settings.composio_outlook_auth_config_id,
        config={"auth_scheme": "OAUTH2"},
        callback_url=f"{settings.api_base_url}/auth/microsoft/callback?state={state}",
    )
    return RedirectResponse(connection.redirect_url)


@router.get("/microsoft/callback")
async def microsoft_callback(request: Request, state: str = ""):
    """Microsoft OAuth done — mail + calendar are both ready."""
    user_id = _verify_state(state)

    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.has_microsoft = True
            await session.commit()

    if user:
        await send_whatsapp_message(
            to=user.phone,
            text="Microsoft connected. Outlook email and calendar are ready to go.",
        )

    logger.info("Microsoft OAuth completed for user %s (Outlook mail + calendar via Composio)", user_id)
    return HTMLResponse(
        "<h2>Microsoft connected! You can close this tab and go back to WhatsApp.</h2>"
    )


# ---------- Canvas ----------


@router.get("/canvas/login")
async def canvas_login(user_id: str):
    """Canvas uses paste-token flow via WhatsApp, not browser redirect.

    This endpoint exists as a fallback / informational page.
    """
    return HTMLResponse(
        "<h2>To connect Canvas, paste your access token directly in WhatsApp.</h2>"
        "<p>Go to Canvas &rarr; Account &rarr; Settings &rarr; New Access Token, "
        "then paste the token in your WhatsApp chat with Aura.</p>"
    )
