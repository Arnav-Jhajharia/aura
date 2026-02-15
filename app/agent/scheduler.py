"""Scheduler — runs Donna's proactive loop for all active users."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from db.models import User
from db.session import async_session
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


def start_scheduler():
    """Register the Donna loop job and start the scheduler."""
    scheduler.add_job(
        run_donna_for_all_users,
        IntervalTrigger(minutes=LOOP_INTERVAL_MINUTES),
        id="donna_loop",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — Donna loop every %d minutes", LOOP_INTERVAL_MINUTES)
