"""Signal aggregator — runs all collectors for a user and returns combined signals."""

import asyncio
import logging

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

logger = logging.getLogger(__name__)

_MAX_SIGNALS = 10


async def collect_all_signals(user_id: str) -> list[Signal]:
    """Run all signal collectors concurrently and return combined results.

    Collectors that fail (e.g. integration not connected) return empty lists
    and don't block other collectors.
    """
    # Look up user timezone
    async with async_session() as session:
        result = await session.execute(select(User.timezone).where(User.id == user_id))
        user_tz = result.scalar_one_or_none() or "UTC"

    collectors = [
        ("calendar", collect_calendar_signals, (user_id, user_tz)),
        ("canvas", collect_canvas_signals, (user_id,)),
        ("email", collect_email_signals, (user_id,)),
        ("internal", collect_internal_signals, (user_id, user_tz)),
    ]

    async def _safe_collect(name: str, fn, args: tuple) -> list[Signal]:
        try:
            return await fn(*args)
        except Exception:
            logger.exception("Signal collector '%s' failed for user %s", name, user_id)
            return []

    results = await asyncio.gather(
        *[_safe_collect(name, fn, args) for name, fn, args in collectors]
    )

    all_signals = [sig for batch in results for sig in batch]

    # Deduplicate
    all_signals = await deduplicate_signals(user_id, all_signals)

    # Cross-signal enrichment
    all_signals = enrich_signals(all_signals)

    # Sort by urgency hint descending so the brain sees high-urgency first
    all_signals.sort(key=lambda s: s.urgency_hint, reverse=True)

    # Cap output
    if len(all_signals) > _MAX_SIGNALS:
        logger.info(
            "Truncating signals from %d to %d for user %s",
            len(all_signals), _MAX_SIGNALS, user_id,
        )
        all_signals = all_signals[:_MAX_SIGNALS]

    logger.info(
        "Collected %d signals for user %s: %s",
        len(all_signals),
        user_id,
        ", ".join(s.type.value for s in all_signals) or "(none)",
    )

    return all_signals
