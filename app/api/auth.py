import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from config import settings
from db.models import User
from db.session import async_session
from tools.composio_client import initiate_connection
from tools.whatsapp import send_whatsapp_message

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------- Google OAuth (via Composio) ----------
# Gmail and Google Calendar are separate Composio apps, each needing their own
# auth config. We chain them: Gmail first → callback initiates Calendar → done.


@router.get("/google/login")
async def google_login(user_id: str):
    """Start Google OAuth — initiate Gmail connection first."""
    connection = await initiate_connection(
        user_id=user_id,
        auth_config_id=settings.composio_gmail_auth_config_id,
        config={"auth_scheme": "OAUTH2"},
        callback_url=f"{settings.api_base_url}/auth/google/callback/gmail?user_id={user_id}",
    )
    return RedirectResponse(connection.redirect_url)


@router.get("/google/callback/gmail")
async def google_callback_gmail(request: Request, user_id: str = ""):
    """Gmail OAuth done — now initiate Google Calendar connection."""
    logger.info("Gmail connected for user %s, chaining Calendar auth...", user_id)
    connection = await initiate_connection(
        user_id=user_id,
        auth_config_id=settings.composio_gcal_auth_config_id,
        config={"auth_scheme": "OAUTH2"},
        callback_url=f"{settings.api_base_url}/auth/google/callback/calendar?user_id={user_id}",
    )
    return RedirectResponse(connection.redirect_url)


@router.get("/google/callback/calendar")
async def google_callback_calendar(request: Request, user_id: str = ""):
    """Both Gmail and Calendar are now connected. Confirm to the user."""
    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

    if user:
        await send_whatsapp_message(
            to=user.phone,
            text="Google connected. Calendar and Gmail are ready to go.",
        )

    logger.info("Google OAuth completed for user %s (Gmail + Calendar via Composio)", user_id)
    return HTMLResponse(
        "<h2>Google connected! You can close this tab and go back to WhatsApp.</h2>"
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
