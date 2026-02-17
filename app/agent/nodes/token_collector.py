import logging

import httpx
from sqlalchemy import select

from agent.state import AuraState
from config import settings
from db.models import OAuthToken, User, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)


def _looks_like_canvas_token(text: str) -> bool:
    """Canvas PATs are typically 64+ char alphanumeric strings, no spaces."""
    if not text or len(text) < 50:
        return False
    if " " in text:
        return False
    # Opt-out / conversational phrases — hand off to main flow for natural response
    lower = text.lower()
    if any(w in lower for w in (
        "no", "don't", "dont", "nah", "nope", "nevermind", "cancel", "skip", "later",
        "hey", "hello", "hi", "wanna", "want", "just", "contacted", "hold", "wait",
        "sorry", "wrong", "oops", "forget", "changed", "mind", "actually", "?",
    )):
        return False
    return True


async def _validate_canvas_token(token: str) -> bool:
    """Hit /api/v1/users/self to confirm the token works."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.canvas_base_url}/api/v1/users/self",
                headers={"Authorization": f"Bearer {token}"},
            )
        return resp.status_code == 200
    except Exception:
        return False


async def token_collector(state: AuraState) -> dict:
    """Handle pending token-collection actions.

    pending_action values handled:
      connect_canvas        → send instructions + set awaiting_canvas_token
      awaiting_canvas_token → validate PAT, store in OAuthToken, confirm
    """
    user_id = state["user_id"]
    action = state.get("pending_action")
    user_input = (state.get("transcription") or state.get("raw_input", "")).strip()

    # ── User tapped "Connect Google" button ──────────────────────────────────
    if action == "connect_google" or user_input == "connect_google":
        google_url = (
            f"{settings.api_base_url}/auth/google/login?user_id={user_id}"
        )
        return {
            "response": f"Tap the link to connect Google Calendar and Gmail:\n{google_url}",
        }

    # ── User tapped "Connect Outlook" button ──────────────────────────────
    if action == "connect_microsoft" or user_input == "connect_microsoft":
        microsoft_url = (
            f"{settings.api_base_url}/auth/microsoft/login?user_id={user_id}"
        )
        return {
            "response": f"Tap the link to connect Outlook email and calendar:\n{microsoft_url}",
        }

    # ── User tapped "Connect Canvas" button ──────────────────────────────────
    if action == "connect_canvas" or user_input == "connect_canvas":
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()
            user.pending_action = "awaiting_canvas_token"
            await session.commit()
        canvas_url = f"{settings.canvas_base_url}/profile/settings"
        return {
            "pending_action": "awaiting_canvas_token",
            "response": (
                "To connect Canvas:\n\n"
                f"1. Open Canvas → *Account* → *Settings*\n"
                f"   {canvas_url}\n"
                "2. Scroll to *Approved Integrations*\n"
                "3. Tap *New Access Token* → set a name, add an expiry\n"
                "4. Copy the token and paste it here."
            ),
        }

    # ── User pasted their Canvas token (or pasted one without tapping the button) ─
    if action == "awaiting_canvas_token" or (action is None and _looks_like_canvas_token(user_input)):
        # User might be saying something else (opt-out, chat, question) — hand off to main flow
        if not _looks_like_canvas_token(user_input):
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one()
                user.pending_action = None
                await session.commit()
            return {
                "pending_action": None,
                "response": None,
                "handoff_to_main": True,
            }

        token = user_input
        valid = await _validate_canvas_token(token)
        if not valid:
            return {
                "response": (
                    "That token didn't work — double-check you copied the full thing. "
                    "Try again."
                ),
            }

        # Store Canvas PAT in OAuthToken (Canvas uses direct httpx, not Composio)
        async with async_session() as session:
            existing = await session.execute(
                select(OAuthToken).where(
                    OAuthToken.user_id == user_id,
                    OAuthToken.provider == "canvas",
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                row.access_token = token
            else:
                session.add(OAuthToken(
                    id=generate_uuid(),
                    user_id=user_id,
                    provider="canvas",
                    access_token=token,
                ))

            # Clear pending action
            user_result = await session.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one()
            user.pending_action = None
            await session.commit()

        return {
            "pending_action": None,
            "response": "Canvas connected. I can see your assignments and grades now.",
        }

    # Shouldn't reach here
    logger.warning("token_collector called with unexpected action=%s", action)
    return {"response": None}
