"""Metrics collection and assertions for simulation tests.

Tracks per-user time series of sends, replies, categories, and
violations. Provides assertion methods that detect real bugs.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)


@dataclass
class SendEvent:
    user_id: str
    timestamp: datetime
    category: str
    message: str
    hour: int
    day: int  # day of simulation

    @property
    def date(self) -> date:
        return self.timestamp.date()


@dataclass
class ReplyEvent:
    user_id: str
    timestamp: datetime
    category: str
    sentiment: str
    text: str


@dataclass
class Violation:
    user_id: str
    archetype: str
    violation_type: str
    detail: str
    timestamp: datetime | None = None


@dataclass
class SimReport:
    """Complete simulation results with assertion methods."""

    sends: list[SendEvent] = field(default_factory=list)
    replies: list[ReplyEvent] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    archetype_names: dict[str, str] = field(default_factory=dict)  # user_id → name
    days_simulated: int = 0
    reflection_count: int = 0

    # ── Computed aggregates ──────────────────────────────────────────────

    def sends_for(self, user_id: str) -> list[SendEvent]:
        return [s for s in self.sends if s.user_id == user_id]

    def sends_by_archetype(self, name: str) -> list[SendEvent]:
        uid = self._uid_for(name)
        return self.sends_for(uid) if uid else []

    def weekly_send_counts(self, user_id: str) -> list[int]:
        """Sends per week (7-day buckets)."""
        by_week: dict[int, int] = defaultdict(int)
        for s in self.sends_for(user_id):
            week = s.day // 7
            by_week[week] += 1
        weeks = self.days_simulated // 7 or 1
        return [by_week.get(w, 0) for w in range(weeks)]

    def daily_send_counts(self, user_id: str) -> dict[int, int]:
        by_day: dict[int, int] = defaultdict(int)
        for s in self.sends_for(user_id):
            by_day[s.day] += 1
        return dict(by_day)

    def categories_for(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for s in self.sends_for(user_id):
            counts[s.category] += 1
        return dict(counts)

    def engagement_rate(self, user_id: str) -> float:
        sends = len(self.sends_for(user_id))
        replies = len([r for r in self.replies if r.user_id == user_id])
        return replies / sends if sends > 0 else 0.0

    def first_send_hour(self, user_id: str) -> int | None:
        """Hours from sim start to first proactive message."""
        user_sends = self.sends_for(user_id)
        if not user_sends:
            return None
        return user_sends[0].day * 24 + user_sends[0].hour

    def first_explicit_stop(self, user_id: str, category: str) -> int | None:
        """Day of first explicit_stop reply for given category."""
        for r in self.replies:
            if r.user_id == user_id and r.sentiment == "explicit_stop" and category in r.text:
                return (r.timestamp - self.sends[0].timestamp).days if self.sends else None
        return None

    def _uid_for(self, archetype_name: str) -> str | None:
        for uid, name in self.archetype_names.items():
            if name == archetype_name:
                return uid
        return None

    # ── Assertion methods ────────────────────────────────────────────────

    def assert_no_hard_failures(self):
        """Hard invariants — any violation here is a bug."""
        hard = [v for v in self.violations if v.violation_type in (
            "quiet_hour_violation", "cooldown_violation", "cap_violation",
        )]
        if hard:
            details = "\n".join(f"  [{v.violation_type}] {v.archetype}: {v.detail}" for v in hard)
            raise AssertionError(f"{len(hard)} hard violations:\n{details}")

    def assert_hostile_user_respected(self):
        """After explicit_stop for a category, no messages of that category should follow."""
        suppression = [v for v in self.violations if v.violation_type == "suppression_violation"]
        if suppression:
            details = "\n".join(f"  {v.archetype}: {v.detail}" for v in suppression)
            raise AssertionError(f"{len(suppression)} suppression violations:\n{details}")

    def assert_no_negative_spirals(self):
        """Active non-hostile users should get at least 1 msg/week."""
        for uid, name in self.archetype_names.items():
            if name in ("hostile",):
                continue  # hostile users may get silenced
            weekly = self.weekly_send_counts(uid)
            if len(weekly) < 2:
                continue
            # Check for 2+ consecutive weeks with 0 sends (after week 1)
            consecutive_zero = 0
            max_zero = 0
            for w in weekly[1:]:  # skip week 0 (cold start)
                if w == 0:
                    consecutive_zero += 1
                    max_zero = max(max_zero, consecutive_zero)
                else:
                    consecutive_zero = 0
            if max_zero >= 2:
                raise AssertionError(
                    f"{name} ({uid}): {max_zero} consecutive weeks with 0 messages "
                    f"(negative spiral). Weekly: {weekly}"
                )

    def assert_category_diversity(self):
        """Non-hostile users with 10+ messages should have at least 2 categories."""
        for uid, name in self.archetype_names.items():
            if name in ("hostile", "newuser"):
                continue
            cats = self.categories_for(uid)
            total = sum(cats.values())
            if total >= 10 and len(cats) < 2:
                raise AssertionError(
                    f"{name} ({uid}): only {len(cats)} category with {total} messages. "
                    f"Categories: {cats}"
                )

    def assert_cold_start_converges(self):
        """New user should receive first proactive message within 72 hours."""
        uid = self._uid_for("newuser")
        if not uid:
            return
        first = self.first_send_hour(uid)
        if first is None or first > 72:
            raise AssertionError(
                f"newuser: first message at hour {first} (expected < 72)"
            )

    # ── Printing ─────────────────────────────────────────────────────────

    def print_summary(self):
        """Human-readable summary of the simulation."""
        print(f"\n{'=' * 70}")
        print(f"SIMULATION REPORT — {self.days_simulated} days, "
              f"{len(self.archetype_names)} users, {self.reflection_count} reflections")
        print(f"{'=' * 70}")

        for uid, name in sorted(self.archetype_names.items(), key=lambda x: x[1]):
            user_sends = self.sends_for(uid)
            user_replies = [r for r in self.replies if r.user_id == uid]
            cats = self.categories_for(uid)
            weekly = self.weekly_send_counts(uid)
            eng = self.engagement_rate(uid)

            print(f"\n  {name.upper()} ({uid[:8]}...)")
            print(f"    Total messages: {len(user_sends)}")
            print(f"    Total replies:  {len(user_replies)}")
            print(f"    Engagement:     {eng:.0%}")
            print(f"    Categories:     {dict(cats)}")
            print(f"    Weekly sends:   {weekly}")

        violations = self.violations
        if violations:
            print(f"\n  VIOLATIONS ({len(violations)}):")
            for v in violations:
                print(f"    [{v.violation_type}] {v.archetype}: {v.detail}")
        else:
            print(f"\n  VIOLATIONS: None")
        print(f"{'=' * 70}\n")


class MetricsCollector:
    """Accumulates events during simulation and builds a SimReport."""

    def __init__(self):
        self.sends: list[SendEvent] = []
        self.replies: list[ReplyEvent] = []
        self.violations: list[Violation] = []
        self.archetype_names: dict[str, str] = {}
        self.days_simulated = 0
        self.reflection_count = 0

        # Track state for violation detection
        self._last_send_time: dict[str, datetime] = {}
        self._daily_send_count: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
        self._explicit_stops: dict[str, set[str]] = defaultdict(set)  # user_id → stopped categories

    def register_user(self, user_id: str, archetype_name: str):
        self.archetype_names[user_id] = archetype_name

    def record_send(self, user_id: str, timestamp: datetime, category: str,
                    message: str, day: int, is_quiet_hour: bool = False):
        """Record a proactive message send and check for violations."""
        event = SendEvent(
            user_id=user_id, timestamp=timestamp, category=category,
            message=message, hour=timestamp.hour, day=day,
        )
        self.sends.append(event)

        name = self.archetype_names.get(user_id, "unknown")

        # Check suppression violation
        if category in self._explicit_stops.get(user_id, set()):
            self.violations.append(Violation(
                user_id=user_id, archetype=name,
                violation_type="suppression_violation",
                detail=f"Sent '{category}' after explicit stop. Message: {message[:60]}",
                timestamp=timestamp,
            ))

        # Check cooldown violation (< 30 min since last send)
        last = self._last_send_time.get(user_id)
        if last and (timestamp - last).total_seconds() < 1800:
            self.violations.append(Violation(
                user_id=user_id, archetype=name,
                violation_type="cooldown_violation",
                detail=f"Sent {(timestamp - last).seconds // 60}min after previous send",
                timestamp=timestamp,
            ))

        # Check daily cap
        d = timestamp.date()
        self._daily_send_count[user_id][d] += 1
        if self._daily_send_count[user_id][d] > 5:
            self.violations.append(Violation(
                user_id=user_id, archetype=name,
                violation_type="cap_violation",
                detail=f"{self._daily_send_count[user_id][d]} messages on {d}",
                timestamp=timestamp,
            ))

        self._last_send_time[user_id] = timestamp

    def record_reply(self, user_id: str, timestamp: datetime, category: str,
                     sentiment: str, text: str):
        self.replies.append(ReplyEvent(
            user_id=user_id, timestamp=timestamp, category=category,
            sentiment=sentiment, text=text,
        ))
        if sentiment == "explicit_stop":
            self._explicit_stops[user_id].add(category)

    def record_reflection(self):
        self.reflection_count += 1

    def generate_report(self) -> SimReport:
        return SimReport(
            sends=self.sends,
            replies=self.replies,
            violations=self.violations,
            archetype_names=self.archetype_names,
            days_simulated=self.days_simulated,
            reflection_count=self.reflection_count,
        )
