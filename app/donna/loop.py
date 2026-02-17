"""Main Donna loop — runs the full proactive pipeline for a single user."""

import logging
from datetime import datetime, timedelta, timezone

from donna.signals.collector import collect_all_signals
from donna.brain.prefilter import prefilter_signals
from donna.brain.context import build_context
from donna.brain.candidates import generate_candidates
from donna.brain.rules import save_deferred_insights, score_and_filter
from donna.brain.sender import send_proactive_message

logger = logging.getLogger(__name__)


async def _try_queue_deferred(user_id: str, signals, trust_info: dict, block_reason: str) -> None:
    """If blocked by quiet hours and there are signals, run the brain pipeline
    and queue the best candidate as a DeferredSend for later delivery."""
    if block_reason != "quiet_hours" or not signals:
        return

    try:
        from donna.brain.context import build_context as _build_ctx
        from donna.brain.candidates import generate_candidates as _gen
        from donna.brain.rules import score_and_filter as _score
        from db.models import DeferredSend, generate_uuid
        from db.session import async_session

        context = await _build_ctx(user_id, signals, trust_info=trust_info)
        candidates = await _gen(context)
        if not candidates:
            return

        approved = _score(candidates, context)
        if not approved:
            return

        best = approved[0]
        scheduled_for = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=6)

        async with async_session() as session:
            session.add(DeferredSend(
                id=generate_uuid(),
                user_id=user_id,
                candidate_json=best,
                block_reason=block_reason,
                scheduled_for=scheduled_for,
            ))
            await session.commit()

        logger.info("Queued deferred send for user %s (scheduled %s)", user_id, scheduled_for)
    except Exception:
        logger.exception("Failed to queue deferred send for user %s", user_id)


async def donna_loop(user_id: str) -> int:
    """Run one full proactive cycle for a user.

    Pipeline: signals → prefilter → context → LLM candidates → scoring/filter → send.

    Returns the number of messages actually sent.
    """
    # 1. Collect signals (calendar, canvas, email, internal)
    signals = await collect_all_signals(user_id)

    if not signals:
        logger.debug("No signals for user %s — skipping brain", user_id)
        return 0

    # 1b. Pre-filter: hard rules (quiet hours, cooldown, daily cap) BEFORE LLM
    signals, should_continue, trust_info, block_reason = await prefilter_signals(user_id, signals)
    if not should_continue:
        logger.debug("Prefilter blocked cycle for user %s (reason=%s)", user_id, block_reason)
        # Queue deferred send if blocked by quiet hours
        await _try_queue_deferred(user_id, signals, trust_info, block_reason)
        return 0

    # 1c. Skip if only context-only signals (time windows, interaction gaps).
    # These alone produce vague filler — we need at least one concrete signal.
    has_concrete = any(not s.data.get("_context_only") for s in signals)
    if not has_concrete:
        logger.debug("Only context-only signals for user %s — skipping brain", user_id)
        return 0

    # 2. Build context window for the LLM
    context = await build_context(user_id, signals, trust_info=trust_info)

    # 3. Generate candidate messages via LLM
    candidates = await generate_candidates(context)

    if not candidates:
        logger.debug("LLM returned no candidates for user %s", user_id)
        return 0

    # 4. Score, filter, and collect deferred insights
    approved = score_and_filter(candidates, context)

    # Save borderline candidates as deferred insights for reactive use
    try:
        await save_deferred_insights(user_id, context)
    except Exception:
        logger.exception("Failed to save deferred insights for user %s", user_id)

    if not approved:
        logger.debug("All candidates filtered out for user %s", user_id)
        return 0

    # 5. Send the top message only (avoid overwhelming the user)
    best = approved[0]
    sent = await send_proactive_message(user_id, best)

    return 1 if sent else 0
