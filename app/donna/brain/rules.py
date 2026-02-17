"""Scorer and filter — applies soft scoring and dedup to candidates.

Hard rules (quiet hours, cooldown, daily cap) have moved to prefilter.py
so they run BEFORE the LLM call.
"""

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from db.models import ChatMessage, DeferredInsight, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)

# Weights for composite score
W_RELEVANCE = 0.4
W_TIMING = 0.35
W_URGENCY = 0.25

# Thresholds
SCORE_THRESHOLD = 5.5          # minimum composite score to send (default)
DEFERRED_MIN_SCORE = 4.0       # minimum score to save as deferred insight
DEFERRED_EXPIRY_HOURS = 24


def score_and_filter(candidates: list[dict], context: dict) -> list[dict]:
    """Score candidates, apply soft filters, return approved messages sorted by score.

    Hard rules (quiet hours, cooldown, daily cap) are now in prefilter.py.
    This function handles: composite scoring, score threshold, dedup.

    Candidates that fall below threshold but above DEFERRED_MIN_SCORE are
    collected in context["_deferred_candidates"] for later saving.
    """
    if not candidates:
        return []

    # ── Recent assistant messages for dedup ─────────────────────────
    recent_messages = [
        m["content"].lower()
        for m in context.get("recent_conversation", [])
        if m.get("role") == "assistant"
    ]

    # Trust-dependent threshold (Phase 2)
    threshold = context.get("score_threshold", SCORE_THRESHOLD)

    # ── Suppressed categories (hard enforcement) ────────────────────
    suppressed = context.get("category_suppression", {}).get("suppressed", {})

    scored: list[dict] = []
    deferred: list[dict] = []

    for candidate in candidates:
        # ── Hard filter: suppressed categories ─────────────────────
        if candidate.get("category") in suppressed:
            logger.debug(
                "Filtered (suppressed category %s): %s",
                candidate["category"],
                candidate["message"][:50],
            )
            continue

        relevance = candidate.get("relevance", 5)
        timing = candidate.get("timing", 5)
        urgency = candidate.get("urgency", 5)

        composite = (
            relevance * W_RELEVANCE
            + timing * W_TIMING
            + urgency * W_URGENCY
        )
        candidate["composite_score"] = round(composite, 2)

        # ── Filter: score threshold ──────────────────────────────────
        if composite < threshold:
            # Exploration budget: 10% chance to allow borderline candidates
            if (
                random.random() < 0.10
                and composite >= threshold - 1.0
                and composite >= DEFERRED_MIN_SCORE
            ):
                candidate["_explored"] = True
                scored.append(candidate)
                logger.debug(
                    "Exploration pass (score %.1f, threshold %.1f): %s",
                    composite, threshold, candidate["message"][:50],
                )
                continue
            if composite >= DEFERRED_MIN_SCORE:
                deferred.append(candidate)
            logger.debug("Filtered (low score %.1f): %s", composite, candidate["message"][:50])
            continue

        # ── Filter: dedup (skip if similar to recent assistant message) ──
        candidate_lower = candidate["message"].lower()
        candidate_words = set(candidate_lower.split())
        is_duplicate = False
        for recent in recent_messages:
            recent_words = set(recent.split())
            if not candidate_words or not recent_words:
                continue
            overlap = len(candidate_words & recent_words) / max(len(candidate_words), 1)
            if overlap > 0.6:
                logger.debug(
                    "Filtered (dedup %.0f%% overlap): %s",
                    overlap * 100,
                    candidate["message"][:50],
                )
                is_duplicate = True
                break
        if is_duplicate:
            continue

        scored.append(candidate)

    # Sort by composite score descending
    scored.sort(key=lambda c: c["composite_score"], reverse=True)

    # Store deferred candidates in context for the loop to save
    if deferred:
        context["_deferred_candidates"] = deferred

    if scored:
        logger.info(
            "Approved %d/%d candidates (top: %.1f '%s')",
            len(scored),
            len(candidates),
            scored[0]["composite_score"],
            scored[0]["message"][:40],
        )

    return scored


async def save_deferred_insights(user_id: str, context: dict) -> None:
    """Save borderline candidates as deferred insights for reactive use."""
    deferred = context.pop("_deferred_candidates", [])
    if not deferred:
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = now + timedelta(hours=DEFERRED_EXPIRY_HOURS)

    async with async_session() as session:
        for candidate in deferred:
            session.add(DeferredInsight(
                id=generate_uuid(),
                user_id=user_id,
                category=candidate.get("category", "nudge"),
                message_draft=candidate["message"],
                trigger_signals=candidate.get("trigger_signals", []),
                relevance_score=candidate.get("composite_score", 0),
                expires_at=expires_at,
            ))
        await session.commit()

    logger.info("Saved %d deferred insights for user %s", len(deferred), user_id)


async def count_proactive_today(user_id: str) -> int:
    """Count how many proactive (assistant) messages were sent today."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as session:
        result = await session.execute(
            select(func.count(ChatMessage.id))
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "assistant",
                ChatMessage.is_proactive.is_(True),
                ChatMessage.created_at >= today_start,
            )
        )
        return result.scalar_one()
