"""Singleton Composio client and async helpers.

All Composio SDK calls are synchronous, so we wrap them with
asyncio.to_thread() to avoid blocking FastAPI's event loop.
"""

import asyncio
import logging

from composio import Composio

from config import settings

logger = logging.getLogger(__name__)

composio = Composio(api_key=settings.composio_api_key)

# Map Composio toolkit names → our internal provider names
_TOOLKIT_MAP = {
    "GMAIL": "google",
    "GOOGLECALENDAR": "google",
    "CANVAS": "canvas",
    "OUTLOOK": "microsoft",
    "MICROSOFTOUTLOOK": "microsoft",
}


async def execute_tool(slug: str, user_id: str, arguments: dict) -> dict:
    """Execute a Composio tool action, returning the result dict."""
    result = await asyncio.to_thread(
        composio.tools.execute,
        slug=slug,
        user_id=user_id,
        arguments=arguments,
        dangerously_skip_version_check=True,
    )
    # Normalise to plain dict if needed
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return dict(result) if not isinstance(result, dict) else result


async def get_connected_integrations(user_id: str) -> list[str]:
    """Return deduplicated provider names the user has active on Composio."""
    connections = await asyncio.to_thread(
        composio.connected_accounts.list,
        user_ids=[user_id],
        statuses=["ACTIVE"],
    )
    providers: set[str] = set()
    for c in connections.items:
        slug = getattr(c.toolkit, "slug", None) or ""
        if slug:
            providers.add(_TOOLKIT_MAP.get(slug.upper(), slug))
    return list(providers)


async def get_email_provider(user_id: str) -> str:
    """Return 'microsoft' or 'google' based on connected integrations."""
    providers = await get_connected_integrations(user_id)
    if "microsoft" in providers:
        return "microsoft"
    if "google" in providers:
        return "google"
    return ""


async def initiate_connection(user_id: str, auth_config_id: str, **kwargs):
    """Initiate a new Composio connection (OAuth2 or API_KEY)."""
    return await asyncio.to_thread(
        composio.connected_accounts.initiate,
        user_id=user_id,
        auth_config_id=auth_config_id,
        **kwargs,
    )
