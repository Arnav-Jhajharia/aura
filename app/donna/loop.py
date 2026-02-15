"""Main Donna loop — runs the full proactive pipeline for a single user."""

import logging

from donna.signals.collector import collect_all_signals
from donna.brain.context import build_context
from donna.brain.candidates import generate_candidates
from donna.brain.rules import score_and_filter
from donna.brain.sender import send_proactive_message

logger = logging.getLogger(__name__)


async def donna_loop(user_id: str) -> int:
    """Run one full proactive cycle for a user.

    Pipeline: signals → context → LLM candidates → scoring/filter → send.

    Returns the number of messages actually sent.
    """
    # 1. Collect signals (calendar, canvas, email, internal)
    signals = await collect_all_signals(user_id)

    if not signals:
        logger.debug("No signals for user %s — skipping brain", user_id)
        return 0

    # 2. Build context window for the LLM
    context = await build_context(user_id, signals)

    # 3. Generate candidate messages via LLM
    candidates = await generate_candidates(context)

    if not candidates:
        logger.debug("LLM returned no candidates for user %s", user_id)
        return 0

    # 4. Score and filter (quiet hours, cooldown, thresholds)
    approved = score_and_filter(candidates, context)

    if not approved:
        logger.debug("All candidates filtered out for user %s", user_id)
        return 0

    # 5. Send the top message only (avoid overwhelming the user)
    best = approved[0]
    sent = await send_proactive_message(user_id, best)

    return 1 if sent else 0
