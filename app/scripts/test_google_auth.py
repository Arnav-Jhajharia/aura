#!/usr/bin/env python3
"""Test Google OAuth and Calendar integration.

Run: python scripts/test_google_auth.py <user_id>

Usage:
  1. Get a user_id from your DB: SELECT id FROM users WHERE phone = '...';
  2. python scripts/test_google_auth.py <user_id>
"""
import asyncio
import sys

# Add project root to path
sys.path.insert(0, ".")

from tools.calendar import create_calendar_event, get_calendar_events
from tools.google_auth import get_valid_google_token


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_google_auth.py <user_id>")
        print()
        print("Get user_id from DB: SELECT id FROM users LIMIT 1;")
        sys.exit(1)

    user_id = sys.argv[1]

    print("1. Checking Google token...")
    token = await get_valid_google_token(user_id)
    if not token:
        print("   FAIL: No Google token found. Connect Google first via the WhatsApp flow.")
        sys.exit(1)
    print("   OK: Token present")

    print("\n2. Fetching calendar events (today)...")
    events = await get_calendar_events(user_id, days=1)
    if events and "error" in events[0]:
        print(f"   FAIL: {events[0]}")
        sys.exit(1)
    print(f"   OK: Found {len(events)} events")

    print("\n3. Creating test event...")
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    start = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    end = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    result = await create_calendar_event(
        user_id,
        title="Aura test event",
        start=start,
        end=end,
    )
    if "error" in result:
        print(f"   FAIL: {result}")
        sys.exit(1)
    print(f"   OK: Event created: {result.get('link', 'N/A')}")

    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
