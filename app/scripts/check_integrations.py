#!/usr/bin/env python3
"""Check that all integrations are working for a user.

Run from app/:
    python scripts/check_integrations.py                  # checks all onboarded users
    python scripts/check_integrations.py --user USER_ID   # specific user
"""

import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select

from db.models import OAuthToken, User
from db.session import async_session

# ANSI
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def check_google(user_id: str) -> tuple[bool, bool]:
    """Check Gmail and Google Calendar via Composio. Returns (gmail_ok, gcal_ok)."""
    from tools.composio_client import get_connected_integrations
    try:
        providers = await get_connected_integrations(user_id)
        has_google = "google" in providers
        return has_google, has_google  # both go through same Composio "google" provider
    except Exception as e:
        print(f"    {RED}Composio error: {e}{RESET}")
        return False, False


async def check_gmail_fetch(user_id: str) -> bool:
    """Try to actually fetch emails."""
    from tools.email import get_emails
    try:
        result = await get_emails(user_id=user_id, filter="unread", count=1)
        if result and isinstance(result[0], dict) and "error" in result[0]:
            print(f"    {DIM}Gmail API: {result[0]['error']}{RESET}")
            return False
        print(f"    {DIM}Gmail: fetched {len(result)} email(s){RESET}")
        return True
    except Exception as e:
        print(f"    {RED}Gmail fetch error: {e}{RESET}")
        return False


async def check_calendar_fetch(user_id: str) -> bool:
    """Try to actually fetch calendar events."""
    from tools.calendar import get_calendar_events
    try:
        result = await get_calendar_events(user_id=user_id, date="today", days=1)
        if result and isinstance(result[0], dict) and "error" in result[0]:
            print(f"    {DIM}Calendar API: {result[0]['error']}{RESET}")
            return False
        print(f"    {DIM}Calendar: fetched {len(result)} event(s) today{RESET}")
        return True
    except Exception as e:
        print(f"    {RED}Calendar fetch error: {e}{RESET}")
        return False


async def check_microsoft(user_id: str) -> tuple[bool, bool]:
    """Check Microsoft Outlook via Composio. Returns (outlook_ok, outlook_cal_ok)."""
    from tools.composio_client import get_connected_integrations
    try:
        providers = await get_connected_integrations(user_id)
        has_ms = "microsoft" in providers
        return has_ms, has_ms  # single OAuth covers both mail + calendar
    except Exception as e:
        print(f"    {RED}Composio error: {e}{RESET}")
        return False, False


async def check_canvas(user_id: str) -> bool:
    """Check Canvas PAT exists and can fetch assignments."""
    async with async_session() as session:
        result = await session.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == "canvas",
            )
        )
        token = result.scalar_one_or_none()

    if not token:
        return False

    from tools.canvas import get_canvas_assignments
    try:
        assignments = await get_canvas_assignments(user_id=user_id, days_ahead=7)
        if assignments and isinstance(assignments[0], dict) and "error" in assignments[0]:
            print(f"    {DIM}Canvas API: {assignments[0]['error']}{RESET}")
            return False
        print(f"    {DIM}Canvas: fetched {len(assignments)} assignment(s) (next 7 days){RESET}")
        return True
    except Exception as e:
        print(f"    {RED}Canvas fetch error: {e}{RESET}")
        return False


async def check_user(user_id: str, user_name: str, user_phone: str, user_tz: str):
    print(f"\n{BOLD}{'=' * 55}{RESET}")
    print(f"{BOLD}  {user_name}  ({user_phone})  tz={user_tz}{RESET}")
    print(f"{BOLD}  id: {user_id}{RESET}")
    print(f"{BOLD}{'=' * 55}{RESET}")

    # Google (Composio)
    gmail_connected, gcal_connected = await check_google(user_id)
    gmail_works = await check_gmail_fetch(user_id) if gmail_connected else False
    gcal_works = await check_calendar_fetch(user_id) if gcal_connected else False

    # Microsoft (Composio)
    outlook_connected, outlook_cal_connected = await check_microsoft(user_id)

    # Canvas
    canvas_works = await check_canvas(user_id)

    # Summary
    print()
    checks = [
        ("Gmail (Composio)", gmail_connected, gmail_works),
        ("Google Calendar (Composio)", gcal_connected, gcal_works),
        ("Outlook Mail (Composio)", outlook_connected, outlook_connected),
        ("Outlook Calendar (Composio)", outlook_cal_connected, outlook_cal_connected),
        ("Canvas (PAT)", canvas_works, canvas_works),
    ]
    all_ok = True
    for name, connected, works in checks:
        if works:
            print(f"  {GREEN}✓ {name} — connected & fetching{RESET}")
        elif connected:
            print(f"  {YELLOW}~ {name} — connected but fetch failed{RESET}")
            all_ok = False
        else:
            print(f"  {RED}✗ {name} — not connected{RESET}")
            all_ok = False

    if all_ok:
        print(f"\n  {GREEN}{BOLD}All integrations working!{RESET}")
    else:
        print(f"\n  {YELLOW}Some integrations need attention.{RESET}")

    return all_ok


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", help="Specific user ID")
    args = parser.parse_args()

    if args.user:
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == args.user))
            user = result.scalar_one_or_none()
        if not user:
            print(f"{RED}User {args.user} not found{RESET}")
            sys.exit(1)
        await check_user(user.id, user.name or "?", user.phone, user.timezone or "UTC")
    else:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.onboarding_complete.is_(True))
            )
            users = result.scalars().all()

        if not users:
            print(f"{YELLOW}No onboarded users found in the database.{RESET}")
            print(f"{DIM}Start the server and onboard via WhatsApp first.{RESET}")
            sys.exit(0)

        print(f"Found {len(users)} onboarded user(s)\n")
        for user in users:
            await check_user(user.id, user.name or "?", user.phone, user.timezone or "UTC")


if __name__ == "__main__":
    asyncio.run(main())
