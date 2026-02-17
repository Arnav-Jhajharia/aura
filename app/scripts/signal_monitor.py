#!/usr/bin/env python3
"""Live signal monitor — watches the full collect→dedup→enrich→cap pipeline.

Run from app/:
    python scripts/signal_monitor.py                     # all onboarded users, 30s interval
    python scripts/signal_monitor.py --user USER_ID      # specific user
    python scripts/signal_monitor.py --interval 10       # poll every 10 seconds
    python scripts/signal_monitor.py --raw               # also show pre-dedup signals
    python scripts/signal_monitor.py --once              # single run, no loop
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from db.models import User
from db.session import async_session
from donna.signals.base import Signal
from donna.signals.calendar import collect_calendar_signals
from donna.signals.canvas import collect_canvas_signals
from donna.signals.dedup import deduplicate_signals
from donna.signals.email import collect_email_signals
from donna.signals.enrichment import enrich_signals
from donna.signals.internal import collect_internal_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("signal_monitor")

_MAX_SIGNALS = 10

# ANSI colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _urgency_color(urgency: int) -> str:
    if urgency >= 8:
        return RED
    if urgency >= 5:
        return YELLOW
    return DIM


def _print_signal(i: int, sig: Signal, prefix: str = ""):
    color = _urgency_color(sig.urgency_hint)
    dedup = f" dedup={sig.dedup_key}" if sig.dedup_key else ""
    enrichment_tags = []
    if sig.data.get("suggested_task"):
        enrichment_tags.append(f"suggested_task={sig.data['suggested_task']}")
    if sig.data.get("care_escalation"):
        enrichment_tags.append("care_escalation")
    if sig.data.get("bedtime_reminder"):
        enrichment_tags.append("bedtime_reminder")
    if sig.data.get("scheduling_hint"):
        enrichment_tags.append("scheduling_hint")
    enrichment = f" {GREEN}[{', '.join(enrichment_tags)}]{RESET}" if enrichment_tags else ""

    # Pick a readable label from data
    label_keys = ["title", "habit_name", "subject", "date", "unread_count", "hours_since"]
    label = ""
    for k in label_keys:
        if k in sig.data:
            label = f" → {sig.data[k]}"
            break

    print(
        f"  {prefix}{color}{i:>2}. [{sig.urgency_hint}] "
        f"{sig.type.value}{RESET}{label}"
        f"{DIM}{dedup}{RESET}{enrichment}"
    )


async def _get_user_tz(user_id: str) -> str:
    async with async_session() as session:
        result = await session.execute(select(User.timezone).where(User.id == user_id))
        return result.scalar_one_or_none() or "UTC"


async def _get_user_name(user_id: str) -> str:
    async with async_session() as session:
        result = await session.execute(select(User.name).where(User.id == user_id))
        return result.scalar_one_or_none() or user_id[:8]


async def run_pipeline(user_id: str, show_raw: bool = False) -> list[Signal]:
    """Run the full signal pipeline with verbose output."""
    user_tz = await _get_user_tz(user_id)
    user_name = await _get_user_name(user_id)
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  {user_name} ({user_id[:12]}…)  tz={user_tz}  {now}{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    # ── Collect raw signals from each source ──────────────────
    collectors = [
        ("calendar", collect_calendar_signals(user_id, user_tz)),
        ("canvas", collect_canvas_signals(user_id)),
        ("email", collect_email_signals(user_id)),
        ("internal", collect_internal_signals(user_id, user_tz)),
    ]

    raw_signals: list[Signal] = []
    for name, coro in collectors:
        try:
            batch = await coro
        except Exception as e:
            print(f"  {RED}✗ {name}: {e}{RESET}")
            continue

        if batch:
            print(f"  {CYAN}◆ {name}{RESET}: {len(batch)} signal(s)")
            if show_raw:
                for i, sig in enumerate(batch, 1):
                    _print_signal(i, sig, prefix=f"{DIM}raw  {RESET}")
            raw_signals.extend(batch)
        else:
            print(f"  {DIM}◇ {name}: 0 signals{RESET}")

    total_raw = len(raw_signals)
    print(f"\n  {BOLD}Raw total: {total_raw}{RESET}")

    if not raw_signals:
        print(f"  {DIM}(nothing to process){RESET}")
        return []

    # ── Dedup ─────────────────────────────────────────────────
    deduped = await deduplicate_signals(user_id, raw_signals)
    dropped = total_raw - len(deduped)
    if dropped:
        print(f"  {YELLOW}Dedup: {total_raw} → {len(deduped)} ({dropped} suppressed){RESET}")
    else:
        print(f"  Dedup: {total_raw} → {len(deduped)} (all new)")

    # ── Enrich ────────────────────────────────────────────────
    enriched = enrich_signals(deduped)
    enrichment_count = sum(
        1 for s in enriched
        if any(k in s.data for k in ("suggested_task", "care_escalation",
                                      "bedtime_reminder", "scheduling_hint"))
    )
    if enrichment_count:
        print(f"  {GREEN}Enrichment: {enrichment_count} signal(s) annotated{RESET}")

    # ── Sort + cap ────────────────────────────────────────────
    enriched.sort(key=lambda s: s.urgency_hint, reverse=True)
    if len(enriched) > _MAX_SIGNALS:
        print(f"  {YELLOW}Cap: {len(enriched)} → {_MAX_SIGNALS}{RESET}")
        enriched = enriched[:_MAX_SIGNALS]

    # ── Final output ──────────────────────────────────────────
    print(f"\n  {BOLD}Final signals → brain ({len(enriched)}):{RESET}")
    for i, sig in enumerate(enriched, 1):
        _print_signal(i, sig)

    return enriched


async def get_user_ids(specific_user: str | None) -> list[str]:
    if specific_user:
        return [specific_user]
    async with async_session() as session:
        result = await session.execute(
            select(User.id).where(User.onboarding_complete.is_(True))
        )
        return [row[0] for row in result.all()]


async def main():
    parser = argparse.ArgumentParser(description="Live signal pipeline monitor")
    parser.add_argument("--user", help="Specific user ID (default: all onboarded)")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")
    parser.add_argument("--raw", action="store_true", help="Show pre-dedup raw signals")
    parser.add_argument("--once", action="store_true", help="Single run, no loop")
    args = parser.parse_args()

    cycle = 0
    while True:
        cycle += 1
        user_ids = await get_user_ids(args.user)

        if not user_ids:
            print(f"{DIM}No onboarded users found.{RESET}")
        else:
            print(f"\n{BOLD}▶ Cycle {cycle} — {len(user_ids)} user(s){RESET}")
            for uid in user_ids:
                try:
                    await run_pipeline(uid, show_raw=args.raw)
                except Exception:
                    logger.exception("Pipeline failed for user %s", uid)

        if args.once:
            break

        print(f"\n{DIM}Next poll in {args.interval}s (Ctrl+C to stop){RESET}")
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{DIM}Stopped.{RESET}")
        sys.exit(0)
