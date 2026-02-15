"""Internal signal collector — time-based and DB-derived signals."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ChatMessage, Habit, MemoryFact, MoodLog, Task, User
from db.session import async_session
from donna.signals.base import Signal, SignalType

logger = logging.getLogger(__name__)


async def collect_internal_signals(user_id: str) -> list[Signal]:
    """Generate signals from internal state: time, mood, tasks, interaction gaps."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    signals: list[Signal] = []

    async with async_session() as session:
        # ── Load user profile ────────────────────────────────────────
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return []

        wake_hour = int((user.wake_time or "08:00").split(":")[0])
        sleep_hour = int((user.sleep_time or "23:00").split(":")[0])
        current_hour = now.hour  # NOTE: should be user's local time; using UTC for now

        # ── Morning / evening window ─────────────────────────────────
        if abs(current_hour - wake_hour) <= 1:
            signals.append(Signal(
                type=SignalType.TIME_MORNING_WINDOW,
                user_id=user_id,
                data={"wake_time": user.wake_time, "user_name": user.name or ""},
            ))

        if abs(current_hour - sleep_hour) <= 1:
            signals.append(Signal(
                type=SignalType.TIME_EVENING_WINDOW,
                user_id=user_id,
                data={"sleep_time": user.sleep_time, "user_name": user.name or ""},
            ))

        # ── Time since last interaction ──────────────────────────────
        last_msg_result = await session.execute(
            select(ChatMessage.created_at)
            .where(ChatMessage.user_id == user_id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        last_msg_row = last_msg_result.scalar_one_or_none()
        if last_msg_row:
            hours_since = (now - last_msg_row).total_seconds() / 3600
            if hours_since >= 6:
                signals.append(Signal(
                    type=SignalType.TIME_SINCE_LAST_INTERACTION,
                    user_id=user_id,
                    data={"hours_since": round(hours_since, 1)},
                ))

        # ── Mood trend (last 7 days) ─────────────────────────────────
        seven_days_ago = now - timedelta(days=7)
        mood_result = await session.execute(
            select(MoodLog)
            .where(MoodLog.user_id == user_id, MoodLog.created_at >= seven_days_ago)
            .order_by(MoodLog.created_at.asc())
        )
        moods = mood_result.scalars().all()

        if len(moods) >= 3:
            scores = [m.score for m in moods]
            recent_avg = sum(scores[-3:]) / 3
            overall_avg = sum(scores) / len(scores)

            if recent_avg <= 4 and recent_avg < overall_avg - 1:
                signals.append(Signal(
                    type=SignalType.MOOD_TREND_DOWN,
                    user_id=user_id,
                    data={
                        "recent_avg": round(recent_avg, 1),
                        "overall_avg": round(overall_avg, 1),
                        "last_score": scores[-1],
                        "days_tracked": len(moods),
                    },
                ))
            elif recent_avg >= 7 and recent_avg > overall_avg + 1:
                signals.append(Signal(
                    type=SignalType.MOOD_TREND_UP,
                    user_id=user_id,
                    data={
                        "recent_avg": round(recent_avg, 1),
                        "overall_avg": round(overall_avg, 1),
                        "last_score": scores[-1],
                    },
                ))

        # ── Overdue tasks ────────────────────────────────────────────
        overdue_result = await session.execute(
            select(Task).where(
                Task.user_id == user_id,
                Task.status == "pending",
                Task.due_date.isnot(None),
                Task.due_date < now,
            )
        )
        overdue_tasks = overdue_result.scalars().all()
        for task in overdue_tasks:
            signals.append(Signal(
                type=SignalType.TASK_OVERDUE,
                user_id=user_id,
                data={
                    "title": task.title,
                    "due_date": task.due_date.isoformat(),
                    "hours_overdue": round(
                        (now - task.due_date).total_seconds() / 3600, 1
                    ),
                    "priority": task.priority,
                    "source": task.source,
                },
            ))

        # ── Tasks due today ──────────────────────────────────────────
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        due_today_result = await session.execute(
            select(Task).where(
                Task.user_id == user_id,
                Task.status == "pending",
                Task.due_date.isnot(None),
                Task.due_date >= now,
                Task.due_date < today_end,
            )
        )
        due_today = due_today_result.scalars().all()
        for task in due_today:
            signals.append(Signal(
                type=SignalType.TASK_DUE_TODAY,
                user_id=user_id,
                data={
                    "title": task.title,
                    "due_date": task.due_date.isoformat(),
                    "priority": task.priority,
                    "source": task.source,
                },
            ))

        # ── Habit streak at risk ────────────────────────────────────
        habit_result = await session.execute(
            select(Habit).where(Habit.user_id == user_id)
        )
        habits = habit_result.scalars().all()

        for habit in habits:
            if not habit.last_logged:
                continue
            last_logged = habit.last_logged
            hours_since_logged = (now - last_logged).total_seconds() / 3600

            if habit.target_frequency == "daily" and hours_since_logged >= 20:
                signals.append(Signal(
                    type=SignalType.HABIT_STREAK_AT_RISK,
                    user_id=user_id,
                    data={
                        "habit_name": habit.name,
                        "current_streak": habit.current_streak,
                        "hours_since_logged": round(hours_since_logged, 1),
                    },
                ))
            elif habit.target_frequency == "weekly" and hours_since_logged >= 144:  # 6 days
                signals.append(Signal(
                    type=SignalType.HABIT_STREAK_AT_RISK,
                    user_id=user_id,
                    data={
                        "habit_name": habit.name,
                        "current_streak": habit.current_streak,
                        "hours_since_logged": round(hours_since_logged, 1),
                    },
                ))

            # Milestone check
            if habit.current_streak > 0 and habit.current_streak % 7 == 0:
                signals.append(Signal(
                    type=SignalType.HABIT_STREAK_MILESTONE,
                    user_id=user_id,
                    data={
                        "habit_name": habit.name,
                        "current_streak": habit.current_streak,
                    },
                ))

        # ── Memory relevance window ────────────────────────────────
        # Check entity:event and entity:place facts that might be relevant now
        # (e.g., Friday evening + empty calendar + restaurant memory)
        day_name = now.strftime("%A").lower()
        is_evening = 17 <= current_hour <= 21
        is_weekend = day_name in ("friday", "saturday", "sunday")

        if is_evening or is_weekend:
            event_facts = await session.execute(
                select(MemoryFact)
                .where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.category.in_(["entity:place", "entity:event"]),
                )
                .order_by(MemoryFact.created_at.desc())
                .limit(5)
            )
            relevant_facts = event_facts.scalars().all()
            if relevant_facts:
                signals.append(Signal(
                    type=SignalType.MEMORY_RELEVANCE_WINDOW,
                    user_id=user_id,
                    data={
                        "reason": "evening/weekend + stored place/event memories",
                        "facts": [f.fact for f in relevant_facts[:3]],
                        "is_evening": is_evening,
                        "is_weekend": is_weekend,
                    },
                ))

    return signals
