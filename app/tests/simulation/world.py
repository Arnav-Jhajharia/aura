"""SimWorld — deterministic simulated external state for each user.

Generates calendar events, Canvas assignments, email bursts, and
internal signals based on a seeded RNG so simulations are reproducible.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from donna.signals.base import Signal, SignalType
from tests.simulation.archetypes import Archetype


class SimWorld:
    """Maintains a fake external world for one simulated user."""

    def __init__(self, archetype: Archetype, user_id: str, sim_start: datetime, seed: int = 42):
        self.archetype = archetype
        self.user_id = user_id
        self.sim_start = sim_start
        self.rng = random.Random(seed)

        self.classes = self._generate_weekly_classes()
        self.assignments = self._generate_assignments()
        self.email_burst_days = self._generate_email_bursts()
        self.habit_name = self.rng.choice(["gym", "reading", "meditation", "running"])

    # ── Generators ────────────────────────────────────────────────────────

    def _generate_weekly_classes(self) -> list[dict]:
        """Generate 5-6 weekly classes with fixed day-of-week + hour."""
        courses = ["CS2103", "IS1108", "MA2001", "ST2334", "CS2040S", "ES2660"]
        self.rng.shuffle(courses)
        classes = []
        for i, course in enumerate(courses[:self.rng.randint(4, 6)]):
            classes.append({
                "title": f"{course} Lecture",
                "day_of_week": i % 5,  # Mon-Fri
                "hour": self.rng.choice([9, 10, 11, 14, 15, 16]),
                "duration_hours": self.rng.choice([1, 2]),
            })
        return classes

    def _generate_assignments(self) -> list[dict]:
        """Generate 8-12 assignments spread over 30 days."""
        assignments = []
        courses = [c["title"].split()[0] for c in self.classes]
        for i in range(self.rng.randint(8, 12)):
            due_day = self.rng.randint(3, 30)
            due_hour = self.rng.choice([23, 17, 12])
            assignments.append({
                "title": f"{self.rng.choice(courses)} Assignment {i + 1}",
                "due_at": self.sim_start + timedelta(days=due_day, hours=due_hour - 8),
                "submitted": False,
            })
        return sorted(assignments, key=lambda a: a["due_at"])

    def _generate_email_bursts(self) -> set[int]:
        """Days when email volume spikes (5+ unread)."""
        return {self.rng.randint(1, 30) for _ in range(self.rng.randint(6, 12))}

    # ── Signal generation per timestep ────────────────────────────────────

    def get_signals(self, sim_time: datetime) -> list[Signal]:
        """Return all signals that should fire at this moment."""
        signals: list[Signal] = []
        hour = sim_time.hour
        day_of_sim = (sim_time - self.sim_start).days
        dow = sim_time.weekday()

        # ── Calendar signals ──
        for cls in self.classes:
            if cls["day_of_week"] == dow:
                class_start = sim_time.replace(hour=cls["hour"], minute=0, second=0, microsecond=0)
                minutes_until = (class_start - sim_time).total_seconds() / 60

                if 0 < minutes_until <= 60:
                    signals.append(Signal(
                        type=SignalType.CALENDAR_EVENT_APPROACHING,
                        user_id=self.user_id,
                        data={"title": cls["title"], "start": class_start.isoformat(),
                              "minutes_until": int(minutes_until)},
                    ))
                elif -15 <= minutes_until <= 0:
                    signals.append(Signal(
                        type=SignalType.CALENDAR_EVENT_STARTED,
                        user_id=self.user_id,
                        data={"title": cls["title"]},
                    ))

        # Calendar gap: if no class for 2+ hours from now
        has_class_soon = any(
            c["day_of_week"] == dow
            and 0 < (sim_time.replace(hour=c["hour"], minute=0) - sim_time).total_seconds() / 3600 < 2
            for c in self.classes
        )
        if not has_class_soon and 10 <= hour <= 18:
            signals.append(Signal(
                type=SignalType.CALENDAR_GAP_DETECTED,
                user_id=self.user_id,
                data={"gap_hours": 2, "start": sim_time.isoformat()},
            ))

        # Busy day: 5+ classes on same day
        today_classes = [c for c in self.classes if c["day_of_week"] == dow]
        if len(today_classes) >= 4 and hour == int(self.archetype.wake_time.split(":")[0]):
            signals.append(Signal(
                type=SignalType.CALENDAR_BUSY_DAY,
                user_id=self.user_id,
                data={"event_count": len(today_classes), "date": sim_time.date().isoformat()},
            ))

        # ── Canvas deadline signals ──
        for asgn in self.assignments:
            if asgn["submitted"]:
                continue
            hours_until_due = (asgn["due_at"] - sim_time).total_seconds() / 3600

            if -48 < hours_until_due < 0:
                signals.append(Signal(
                    type=SignalType.CANVAS_OVERDUE,
                    user_id=self.user_id,
                    data={"title": asgn["title"], "due_at": asgn["due_at"].isoformat(),
                          "hours_overdue": abs(int(hours_until_due))},
                ))
            elif 0 < hours_until_due <= 72:
                signals.append(Signal(
                    type=SignalType.CANVAS_DEADLINE_APPROACHING,
                    user_id=self.user_id,
                    data={"title": asgn["title"], "due_at": asgn["due_at"].isoformat(),
                          "hours_until_due": int(hours_until_due)},
                ))

        # ── Email signals ──
        if day_of_sim in self.email_burst_days and hour == 10:
            signals.append(Signal(
                type=SignalType.EMAIL_UNREAD_PILING,
                user_id=self.user_id,
                data={"unread_count": self.rng.randint(5, 15), "_context_only": False},
            ))

        # ── Internal time signals ──
        wake_h = int(self.archetype.wake_time.split(":")[0])
        sleep_h = int(self.archetype.sleep_time.split(":")[0])

        if hour == wake_h:
            signals.append(Signal(
                type=SignalType.TIME_MORNING_WINDOW,
                user_id=self.user_id,
                data={"_context_only": True},
            ))
        if hour == sleep_h - 2 and sleep_h - 2 > 0:
            signals.append(Signal(
                type=SignalType.TIME_EVENING_WINDOW,
                user_id=self.user_id,
                data={"_context_only": True},
            ))

        # ── Mood signals ──
        mood = self.archetype.mood_score(day_of_sim)
        if mood <= 4 and hour == 15:
            signals.append(Signal(
                type=SignalType.MOOD_TREND_DOWN,
                user_id=self.user_id,
                data={"recent_avg": mood, "overall_avg": 6, "_context_only": False},
            ))

        # ── Habit signals (streak at risk if evening and not logged) ──
        if hour == 20 and day_of_sim % 2 == 0:  # every other day risk
            signals.append(Signal(
                type=SignalType.HABIT_STREAK_AT_RISK,
                user_id=self.user_id,
                data={"habit_name": self.habit_name, "current_streak": max(1, day_of_sim),
                      "hours_since_logged": 22},
            ))

        # ── Memory relevance (weekends + evenings) ──
        if dow >= 5 and 17 <= hour <= 21:
            signals.append(Signal(
                type=SignalType.MEMORY_RELEVANCE_WINDOW,
                user_id=self.user_id,
                data={"_context_only": True, "memory_type": "place",
                      "fact": "mentioned a ramen place near PGP"},
            ))

        # Compute dedup keys
        for s in signals:
            s.compute_dedup_key()

        return signals

    def mark_assignment_submitted(self, title: str) -> None:
        """Mark an assignment as submitted (reduces future signals)."""
        for a in self.assignments:
            if a["title"] == title:
                a["submitted"] = True
                break
