"""Signal aggregator — runs all collectors for a user and returns combined signals."""

import asyncio
import logging
from datetime import datetime, timezone

from donna.signals.base import Signal
from donna.signals.calendar import collect_calendar_signals
from donna.signals.canvas import collect_canvas_signals
from donna.signals.email import collect_email_signals
from donna.signals.internal import collect_internal_signals

logger = logging.getLogger(__name__)


async def collect_all_signals(user_id: str) -> list[Signal]:
    """Run all signal collectors concurrently and return combined results.

    Collectors that fail (e.g. integration not connected) return empty lists
    and don't block other collectors.
    """
    collectors = [
        ("calendar", collect_calendar_signals),
        ("canvas", collect_canvas_signals),
        ("email", collect_email_signals),
        ("internal", collect_internal_signals),
    ]

    async def _safe_collect(name: str, fn) -> list[Signal]:
        try:
            return await fn(user_id)
        except Exception:
            logger.exception("Signal collector '%s' failed for user %s", name, user_id)
            return []

    results = await asyncio.gather(
        *[_safe_collect(name, fn) for name, fn in collectors]
    )

    all_signals = [sig for batch in results for sig in batch]

    # Sort by urgency hint descending so the brain sees high-urgency first
    all_signals.sort(key=lambda s: s.urgency_hint, reverse=True)

    logger.info(
        "Collected %d signals for user %s: %s",
        len(all_signals),
        user_id,
        ", ".join(s.type.value for s in all_signals) or "(none)",
    )

    return all_signals
