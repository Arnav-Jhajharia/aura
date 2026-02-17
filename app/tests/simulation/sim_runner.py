"""Simulation runner — orchestrates the full time-accelerated Donna simulation.

Runs the REAL pipeline (donna_loop, prefilter, scoring, feedback, reflection)
with mocked external services (WhatsApp, LLM, signal collectors).
"""

from __future__ import annotations

import contextlib
import logging
import random
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from donna.brain.feedback import check_and_update_feedback
from donna.loop import donna_loop
from donna.reflection import run_reflection
from donna.signals.base import Signal

from tests.simulation.archetypes import (
    ALL_ARCHETYPES, Archetype, Hostile, SIGNAL_TO_CATEGORY,
)
from tests.simulation.conftest import create_sim_user, create_user_message
from tests.simulation.metrics import MetricsCollector, SimReport
from tests.simulation.world import SimWorld

logger = logging.getLogger(__name__)


class _WAResult:
    success = True
    wa_message_id = "wamid_sim"
    error_code = None
    error_message = None
    retryable = False
    fallback_format = None


def _make_dt_mock(current_time: datetime) -> MagicMock:
    """Create a datetime mock that returns sim time."""
    m = MagicMock()
    m.now = lambda tz=None, _t=current_time: (
        _t.replace(tzinfo=None) if tz is None else _t.astimezone(tz)
    )
    m.utcnow = lambda _t=current_time: _t.replace(tzinfo=None)
    m.timedelta = timedelta
    m.timezone = timezone
    return m


def _make_generate_candidates(signals):
    """Create a mock generate_candidates that returns deterministic candidates."""
    candidates = []
    seen: set[str] = set()
    for sig in signals:
        if sig.data.get("_context_only"):
            continue
        cat = SIGNAL_TO_CATEGORY.get(sig.type.value, "nudge")
        if cat in seen:
            continue
        seen.add(cat)
        title = sig.data.get("title", sig.type.value)
        candidates.append({
            "message": f"[SIM] {title} — {cat}",
            "relevance": 7, "timing": 7, "urgency": sig.urgency_hint,
            "trigger_signals": [sig.type.value],
            "category": cat, "action_type": "text",
        })
    candidates = candidates[:3]

    async def _gen(context):
        return candidates
    return _gen


def _build_patches(signals, capture_fn, hour, current_time):
    """Build a list of (target, kwargs) tuples for patching."""
    dt_mock = _make_dt_mock(current_time)
    gen_fn = _make_generate_candidates(signals)

    patches = [
        # Mock collect_all_signals + generate_candidates (skip real LLM entirely)
        ("donna.loop.collect_all_signals", dict(new_callable=AsyncMock, return_value=signals)),
        ("donna.loop.generate_candidates", dict(side_effect=gen_fn)),
        # Mock LLM instances to avoid real API calls
        ("donna.memory.recall.llm", dict(new=AsyncMock())),
        ("donna.brain.template_filler.llm", dict(new=AsyncMock())),
        # WhatsApp sends
        ("donna.brain.sender.send_whatsapp_message", dict(new_callable=AsyncMock, side_effect=capture_fn)),
        ("donna.brain.sender.send_whatsapp_buttons", dict(new_callable=AsyncMock, side_effect=capture_fn)),
        ("donna.brain.sender.send_whatsapp_list", dict(new_callable=AsyncMock, side_effect=capture_fn)),
        ("donna.brain.sender.send_whatsapp_cta_button", dict(new_callable=AsyncMock, side_effect=capture_fn)),
        ("donna.brain.sender.send_whatsapp_template", dict(new_callable=AsyncMock, side_effect=capture_fn)),
        # Time mocks
        ("donna.brain.prefilter._get_local_hour", dict(return_value=hour)),
        ("donna.brain.rules.datetime", dict(new=dt_mock)),
        ("donna.brain.sender.datetime", dict(new=dt_mock)),
        ("donna.brain.feedback.datetime", dict(new=dt_mock)),
        ("donna.brain.context.datetime", dict(new=dt_mock)),
        ("donna.brain.trust.datetime", dict(new=dt_mock)),
    ]
    return patches


@contextlib.contextmanager
def _apply_patches(patch_list):
    """Apply a list of patches using ExitStack to avoid nesting depth issues."""
    with contextlib.ExitStack() as stack:
        for target, kwargs in patch_list:
            stack.enter_context(patch(target, **kwargs))
        yield


async def run_simulation(
    session_factory,
    days: int = 30,
    step_minutes: int = 30,
    archetypes: list[type[Archetype]] | None = None,
    seed: int = 42,
) -> SimReport:
    """Run a full Donna simulation."""
    rng = random.Random(seed)
    metrics = MetricsCollector()
    metrics.days_simulated = days

    sim_start = datetime(2026, 1, 12, 8, 0, tzinfo=timezone.utc)
    archetype_classes = archetypes or ALL_ARCHETYPES
    users: dict[str, tuple[Archetype, SimWorld]] = {}

    # ── 1. Create users ──
    for i, arch_cls in enumerate(archetype_classes):
        arch = arch_cls()
        user_id = f"sim-{arch.name}-{i:03d}"
        await create_sim_user(session_factory, arch, user_id)
        world = SimWorld(arch, user_id, sim_start, seed=seed + i)
        users[user_id] = (arch, world)
        metrics.register_user(user_id, arch.name)

    # ── 2. Time loop ──
    total_steps = (days * 24 * 60) // step_minutes
    last_reflection_day = -1

    for step in range(total_steps):
        current_time = sim_start + timedelta(minutes=step * step_minutes)
        day_of_sim = (current_time - sim_start).days
        hour = current_time.hour

        for user_id, (arch, world) in users.items():
            signals = world.get_signals(current_time)
            if not signals:
                continue

            sent_messages: list[dict] = []

            async def _capture(*args, **kwargs):
                sent_messages.append(kwargs)
                return _WAResult()

            patch_list = _build_patches(signals, _capture, hour, current_time)

            with _apply_patches(patch_list):
                try:
                    sent = await donna_loop(user_id)
                except Exception as e:
                    logger.warning("donna_loop failed for %s step %d: %s", user_id, step, e)
                    sent = 0

            # Record sends
            if sent > 0 and sent_messages:
                msg_data = sent_messages[-1]
                msg_text = msg_data.get("text", msg_data.get("body", "[unknown]"))
                category = "nudge"
                for sig in signals:
                    cat = SIGNAL_TO_CATEGORY.get(sig.type.value, "nudge")
                    if cat in msg_text:
                        category = cat
                        break
                metrics.record_send(user_id, current_time, category, msg_text, day_of_sim)

            # Simulate user replies
            from db.models import ProactiveFeedback
            from sqlalchemy import select as sa_select
            async with session_factory() as session:
                result = await session.execute(
                    sa_select(ProactiveFeedback).where(
                        ProactiveFeedback.user_id == user_id,
                        ProactiveFeedback.outcome == "pending",
                    )
                )
                pending = result.scalars().all()

            for fb in pending:
                fb_sent_at = fb.sent_at
                if fb_sent_at and fb_sent_at.tzinfo is None:
                    fb_sent_at = fb_sent_at.replace(tzinfo=timezone.utc)

                reply = arch.simulate_reply(
                    category=fb.category or "nudge",
                    hour=hour, day=day_of_sim, rng=rng,
                )
                if not reply:
                    continue

                delay_min = arch.reply_delay_minutes(fb.category or "nudge")
                reply_time = fb_sent_at + timedelta(minutes=delay_min)

                if reply_time <= current_time:
                    await create_user_message(
                        session_factory, user_id, reply.text,
                        reply_time.replace(tzinfo=None),
                    )
                    dt_mock = _make_dt_mock(reply_time)
                    with patch("donna.brain.feedback.datetime", new=dt_mock):
                        try:
                            await check_and_update_feedback(user_id, reply.text)
                        except Exception as e:
                            logger.warning("Feedback failed: %s", e)

                    metrics.record_reply(
                        user_id, reply_time, fb.category or "nudge",
                        reply.sentiment, reply.text,
                    )

        # Nightly reflection at 3AM
        if hour == 3 and day_of_sim > last_reflection_day:
            last_reflection_day = day_of_sim
            dt_mock = _make_dt_mock(current_time)
            for user_id in users:
                with patch("donna.reflection.datetime", new=dt_mock):
                    with patch("donna.brain.behaviors.datetime", new=dt_mock):
                        try:
                            await run_reflection(user_id)
                        except Exception as e:
                            logger.warning("Reflection failed for %s day %d: %s",
                                           user_id, day_of_sim, e)
            metrics.record_reflection()

    return metrics.generate_report()


async def run_single_archetype(
    session_factory,
    archetype_name: str,
    days: int = 14,
    step_minutes: int = 30,
    seed: int = 42,
) -> SimReport:
    """Run simulation with a single archetype for focused testing."""
    target = None
    for cls in ALL_ARCHETYPES:
        inst = cls()
        if inst.name == archetype_name:
            target = cls
            break
    if target is None:
        names = [cls().name for cls in ALL_ARCHETYPES]
        raise ValueError(f"Unknown archetype: {archetype_name}. Available: {names}")

    return await run_simulation(
        session_factory, days=days, step_minutes=step_minutes,
        archetypes=[target], seed=seed,
    )
