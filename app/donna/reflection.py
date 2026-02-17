"""Nightly reflection — computes behavioral models and maintains memory health."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import MemoryFact, User, UserBehavior, UserEntity, generate_uuid
from db.session import async_session
from donna.brain.behaviors import BEHAVIOR_COMPUTERS

logger = logging.getLogger(__name__)


async def run_reflection(user_id: str) -> None:
    """Compute all behaviors for a single user, then run memory maintenance."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for key, compute_fn in BEHAVIOR_COMPUTERS.items():
        try:
            result = await compute_fn(user_id)
            value = result["value"]
            sample_size = result["sample_size"]

            if sample_size == 0:
                continue

            confidence = min(1.0, sample_size / 20)  # scales 0→1 over 20 samples

            async with async_session() as session:
                existing = await session.execute(
                    select(UserBehavior).where(
                        UserBehavior.user_id == user_id,
                        UserBehavior.behavior_key == key,
                    )
                )
                behavior = existing.scalar_one_or_none()

                if behavior:
                    behavior.value = value
                    behavior.confidence = confidence
                    behavior.sample_size = sample_size
                    behavior.last_computed = now
                else:
                    session.add(UserBehavior(
                        id=generate_uuid(),
                        user_id=user_id,
                        behavior_key=key,
                        value=value,
                        confidence=confidence,
                        sample_size=sample_size,
                        last_computed=now,
                    ))
                await session.commit()

        except Exception:
            logger.exception("Behavior computation failed for %s/%s", user_id, key)

    # Feedback-derived metrics (category preferences, trends, suppressions, etc.)
    # These are registered in BEHAVIOR_COMPUTERS via feedback_metrics import,
    # so they run as part of the loop above. This explicit call is a safety net.
    try:
        await _compute_feedback_metrics(user_id)
    except Exception:
        logger.exception("Feedback metric computation failed for %s", user_id)

    # Memory maintenance
    try:
        await _decay_unreferenced_facts(user_id)
    except Exception:
        logger.exception("Fact decay failed for user %s", user_id)

    try:
        await _prune_low_confidence(user_id)
    except Exception:
        logger.exception("Fact pruning failed for user %s", user_id)

    try:
        await _consolidate_entities(user_id)
    except Exception:
        logger.exception("Entity consolidation failed for user %s", user_id)

    logger.info("Reflection complete for user %s", user_id)


async def _compute_feedback_metrics(user_id: str) -> None:
    """Compute feedback-derived metrics that aren't in BEHAVIOR_COMPUTERS.

    Currently this updates the cached proactive_engagement_rate on the User model.
    """
    from donna.brain.feedback import get_feedback_summary

    try:
        summary = await get_feedback_summary(user_id)
        if summary["total_sent"] > 0:
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user:
                    user.proactive_engagement_rate = round(summary["engagement_rate"], 3)
                    if summary["avg_response_latency_seconds"] is not None:
                        user.avg_response_latency_seconds = round(
                            summary["avg_response_latency_seconds"], 1
                        )
                    await session.commit()
    except Exception:
        logger.exception("Failed to update engagement rate for user %s", user_id)


# ── Memory maintenance functions ─────────────────────────────────────────


async def _decay_unreferenced_facts(user_id: str) -> None:
    """Reduce confidence of facts not referenced in 14+ days."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=14)

    async with async_session() as session:
        result = await session.execute(
            select(MemoryFact).where(
                MemoryFact.user_id == user_id,
                MemoryFact.confidence > 0.2,
                # last_referenced is NULL (never referenced) or older than cutoff
                (
                    MemoryFact.last_referenced.is_(None)
                    | (MemoryFact.last_referenced < cutoff)
                ),
                MemoryFact.created_at < cutoff,
            )
        )
        facts = result.scalars().all()

        decayed = 0
        for f in facts:
            f.confidence = round(max(0.0, f.confidence - 0.1), 2)
            decayed += 1

        if decayed:
            await session.commit()
            logger.info("Decayed %d unreferenced facts for user %s", decayed, user_id)


async def _prune_low_confidence(user_id: str) -> None:
    """Delete facts with confidence < 0.2 and older than 30 days."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    async with async_session() as session:
        result = await session.execute(
            select(MemoryFact).where(
                MemoryFact.user_id == user_id,
                MemoryFact.confidence < 0.2,
                MemoryFact.created_at < cutoff,
            )
        )
        facts = result.scalars().all()

        pruned = 0
        for f in facts:
            session.delete(f)
            pruned += 1

        if pruned:
            await session.commit()
            logger.info("Pruned %d low-confidence facts for user %s", pruned, user_id)


async def _consolidate_entities(user_id: str) -> None:
    """Merge UserEntity rows with substring-matching normalized names (same type)."""
    async with async_session() as session:
        result = await session.execute(
            select(UserEntity)
            .where(UserEntity.user_id == user_id)
            .order_by(UserEntity.mention_count.desc())
        )
        entities = result.scalars().all()

    if len(entities) < 2:
        return

    # Group by type
    by_type: dict[str, list[UserEntity]] = {}
    for e in entities:
        by_type.setdefault(e.entity_type, []).append(e)

    merged_ids: set[str] = set()

    for entity_type, group in by_type.items():
        for i, primary in enumerate(group):
            if primary.id in merged_ids:
                continue
            for secondary in group[i + 1:]:
                if secondary.id in merged_ids:
                    continue
                # Check if one name is a substring of the other (normalized)
                p_name = primary.name_normalized
                s_name = secondary.name_normalized
                if p_name in s_name or s_name in p_name:
                    # Merge secondary into primary (primary has higher mention_count)
                    async with async_session() as session:
                        p_obj = await session.get(UserEntity, primary.id)
                        s_obj = await session.get(UserEntity, secondary.id)
                        if p_obj and s_obj:
                            p_obj.mention_count += s_obj.mention_count
                            if s_obj.last_mentioned and (
                                not p_obj.last_mentioned
                                or s_obj.last_mentioned > p_obj.last_mentioned
                            ):
                                p_obj.last_mentioned = s_obj.last_mentioned
                            # Merge contexts
                            p_meta = p_obj.metadata_ or {}
                            s_meta = s_obj.metadata_ or {}
                            p_contexts = p_meta.get("contexts", [])
                            s_contexts = s_meta.get("contexts", [])
                            p_meta["contexts"] = (p_contexts + s_contexts)[-10:]
                            p_obj.metadata_ = p_meta
                            session.delete(s_obj)
                            await session.commit()
                    merged_ids.add(secondary.id)

    if merged_ids:
        logger.info("Consolidated %d duplicate entities for user %s", len(merged_ids), user_id)


async def run_reflection_all_users() -> None:
    """Run reflection for all onboarded users."""
    async with async_session() as session:
        result = await session.execute(
            select(User.id).where(User.onboarding_complete.is_(True))
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        return

    logger.info("Running nightly reflection for %d users", len(user_ids))
    for uid in user_ids:
        try:
            await run_reflection(uid)
        except Exception:
            logger.exception("Reflection failed for user %s", uid)
