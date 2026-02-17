"""Scheduler — runs Donna's proactive loop for all active users."""

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from db.models import DeferredSend, User
from db.session import async_session
from donna.brain.sender import send_proactive_message
from donna.loop import donna_loop

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

LOOP_INTERVAL_MINUTES = 5


async def run_donna_for_all_users():
    """Fetch all onboarded users and run the Donna loop for each."""
    async with async_session() as session:
        result = await session.execute(
            select(User.id).where(User.onboarding_complete.is_(True))
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        return

    logger.info("Running Donna loop for %d users", len(user_ids))

    # Run all users concurrently but catch per-user failures
    async def _safe_run(uid: str):
        try:
            sent = await donna_loop(uid)
            if sent:
                logger.info("Donna sent %d message(s) to user %s", sent, uid)
        except Exception:
            logger.exception("Donna loop failed for user %s", uid)

    await asyncio.gather(*[_safe_run(uid) for uid in user_ids])


def _is_stale(candidate: dict, now: datetime) -> bool:
    """Check if a deferred candidate is too old or past its deadline."""
    # If candidate has a deadline that's already passed
    data = candidate.get("data", {})
    if isinstance(data, dict):
        deadline = data.get("due_date") or data.get("deadline")
        if deadline:
            try:
                dl = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
                dl_naive = dl.replace(tzinfo=None) if dl.tzinfo else dl
                if dl_naive < now:
                    return True
            except (ValueError, TypeError):
                pass

    # Candidate created more than 12h ago is stale
    created = candidate.get("_created_at")
    if created:
        try:
            ct = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            ct_naive = ct.replace(tzinfo=None) if ct.tzinfo else ct
            if (now - ct_naive).total_seconds() > 12 * 3600:
                return True
        except (ValueError, TypeError):
            pass

    return False


async def process_deferred_sends() -> None:
    """Process due DeferredSend rows — send or expire."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with async_session() as session:
        result = await session.execute(
            select(DeferredSend)
            .where(
                DeferredSend.attempted.is_(False),
                DeferredSend.expired.is_(False),
                DeferredSend.scheduled_for <= now,
            )
            .limit(20)
        )
        rows = result.scalars().all()

    if not rows:
        return

    logger.info("Processing %d deferred sends", len(rows))

    for row in rows:
        async with async_session() as session:
            # Re-fetch to avoid detached instance
            fresh = await session.get(DeferredSend, row.id)
            if not fresh or fresh.attempted or fresh.expired:
                continue

            candidate = fresh.candidate_json
            if _is_stale(candidate, now):
                fresh.expired = True
                logger.info("Deferred send %s expired (stale)", fresh.id)
                await session.commit()
                continue

            try:
                sent = await send_proactive_message(fresh.user_id, candidate)
                fresh.attempted = True
                if not sent:
                    logger.warning("Deferred send %s failed to deliver", fresh.id)
            except Exception:
                logger.exception("Deferred send %s error", fresh.id)
                fresh.attempted = True

            await session.commit()


async def _run_nightly_reflection():
    """Nightly behavior computation for all users."""
    from donna.reflection import run_reflection_all_users
    try:
        await run_reflection_all_users()
    except Exception:
        logger.exception("Nightly reflection failed")


async def _run_weekly_patterns():
    """Weekly pattern detection (LLM-based) for all users."""
    from donna.memory.patterns import detect_patterns
    async with async_session() as session:
        result = await session.execute(
            select(User.id).where(User.onboarding_complete.is_(True))
        )
        user_ids = [row[0] for row in result.all()]

    for uid in user_ids:
        try:
            await detect_patterns(uid)
        except Exception:
            logger.exception("Pattern detection failed for user %s", uid)


def start_scheduler():
    """Register all scheduler jobs and start."""
    # Donna proactive loop every 5 minutes
    scheduler.add_job(
        run_donna_for_all_users,
        IntervalTrigger(minutes=LOOP_INTERVAL_MINUTES),
        id="donna_loop",
        replace_existing=True,
    )

    # Deferred sends — check every 60 seconds
    scheduler.add_job(
        process_deferred_sends,
        IntervalTrigger(seconds=60),
        id="deferred_sends",
        replace_existing=True,
    )

    # Nightly reflection at 3:00 AM UTC
    scheduler.add_job(
        _run_nightly_reflection,
        CronTrigger(hour=3, minute=0),
        id="nightly_reflection",
        replace_existing=True,
    )

    # Weekly pattern detection on Sundays at 4:00 AM UTC
    scheduler.add_job(
        _run_weekly_patterns,
        CronTrigger(day_of_week="sun", hour=4, minute=0),
        id="weekly_patterns",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — Donna loop every %d min, reflection at 3AM UTC, patterns Sun 4AM UTC",
        LOOP_INTERVAL_MINUTES,
    )
