import logging

from sqlalchemy import select

from agent.state import AuraState
from config import settings
from db.models import OAuthToken
from db.session import async_session
from donna.user_model import get_user_snapshot
from tools.composio_client import get_connected_integrations

logger = logging.getLogger(__name__)


async def thin_context_loader(state: AuraState) -> dict:
    """Load only what every message needs (~300 tokens).

    Pulls:
    - user_profile, user_behaviors (from unified snapshot)
    - connected_integrations (Google/Microsoft from Composio, Canvas from OAuthToken)
    - connection instructions (when integrations missing)

    Heavy context (tasks, moods, expenses, deadlines, deferred insights)
    is now loaded on-demand by the planner via recall_context.
    Conversation history is already loaded by message_ingress.
    """
    user_id = state["user_id"]

    # Preserve fields already set by ingress (timezone, prefs, conversation_history)
    context = {**state.get("user_context", {})}

    # Unified user snapshot (profile + behaviors)
    try:
        snapshot = await get_user_snapshot(user_id)
        if snapshot:
            context["user_profile"] = snapshot.get("profile", {})
            context["user_behaviors"] = snapshot.get("behaviors", {})
            context["memory_facts"] = snapshot.get("memory_facts", [])
    except Exception:
        logger.exception("Failed to load user snapshot for %s", user_id)

    # Connected integrations
    connected = await get_connected_integrations(user_id)

    async with async_session() as session:
        canvas_result = await session.execute(
            select(OAuthToken.provider).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == "canvas",
            )
        )
        if canvas_result.scalar_one_or_none():
            connected.append("canvas")

    context["connected_integrations"] = connected

    # Connection instructions are only injected when the user's message
    # is about connecting an integration.  Previously these were always
    # present, which made the composer pitch Canvas/Google unprompted.
    intent = state.get("intent")
    raw = (state.get("raw_input") or "").lower()
    _connect_keywords = ("connect", "link", "setup", "set up", "integrate", "canvas", "google",
                         "outlook", "microsoft", "gmail", "calendar")
    wants_connection = intent == "command" and any(k in raw for k in _connect_keywords)

    if wants_connection:
        if "canvas" not in connected:
            context["canvas_connection_instructions"] = (
                "1. Open Canvas → Account → Settings\n"
                "2. Scroll to Approved Integrations\n"
                "3. Tap New Access Token → set a name, add an expiry\n"
                "4. Copy the token and paste it here in this chat."
            )
        if "google" not in connected:
            context["google_connection_url"] = (
                f"{settings.api_base_url}/auth/google/login?user_id={user_id}"
            )
            context["google_connection_instructions"] = (
                "Tap this link to connect Calendar and Gmail."
            )

    return {"user_context": context}


# Keep old name as alias for backwards compatibility in imports
context_loader = thin_context_loader
