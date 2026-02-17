"""Signal primitives for Donna's proactive messaging system.

A Signal is a structured event representing something that changed or
is noteworthy about a user's life — an approaching deadline, a free
time block, an unread email, a mood trend, etc.

Signal collectors poll external services and internal state, then emit
signals that the brain layer scores and acts on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SignalType(str, Enum):
    # Calendar
    CALENDAR_EVENT_APPROACHING = "calendar_event_approaching"
    CALENDAR_EVENT_STARTED = "calendar_event_started"
    CALENDAR_GAP_DETECTED = "calendar_gap_detected"
    CALENDAR_BUSY_DAY = "calendar_busy_day"
    CALENDAR_EMPTY_DAY = "calendar_empty_day"

    # Canvas
    CANVAS_DEADLINE_APPROACHING = "canvas_deadline_approaching"
    CANVAS_OVERDUE = "canvas_overdue"
    CANVAS_GRADE_POSTED = "canvas_grade_posted"

    # Email
    EMAIL_UNREAD_PILING = "email_unread_piling"
    EMAIL_IMPORTANT_RECEIVED = "email_important_received"

    # Internal / time-based
    TIME_MORNING_WINDOW = "time_morning_window"
    TIME_EVENING_WINDOW = "time_evening_window"
    TIME_SINCE_LAST_INTERACTION = "time_since_last_interaction"
    MOOD_TREND_DOWN = "mood_trend_down"
    MOOD_TREND_UP = "mood_trend_up"
    TASK_OVERDUE = "task_overdue"
    TASK_DUE_TODAY = "task_due_today"

    # Memory
    MEMORY_RELEVANCE_WINDOW = "memory_relevance_window"

    # Habits
    HABIT_STREAK_AT_RISK = "habit_streak_at_risk"
    HABIT_STREAK_MILESTONE = "habit_streak_milestone"


@dataclass
class Signal:
    type: SignalType
    user_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""
    dedup_key: str = ""
    local_timestamp: str = ""

    def compute_dedup_key(self) -> str:
        """Build a deterministic dedup key from signal type + distinguishing data fields."""
        t = self.type.value
        d = self.data

        # Signals keyed by a unique external ID
        if "id" in d and d["id"]:
            self.dedup_key = f"{t}:{d['id']}"
        # Signals keyed by a title (assignments, tasks, events)
        elif "title" in d:
            self.dedup_key = f"{t}:{d['title']}"
        # Signals keyed by a date (empty/busy day)
        elif "date" in d:
            self.dedup_key = f"{t}:{d['date']}"
        # Signals keyed by habit name
        elif "habit_name" in d:
            self.dedup_key = f"{t}:{d['habit_name']}"
        # Time-window signals: once per day
        elif t.startswith("time_"):
            self.dedup_key = f"{t}:daily"
        # Mood signals: once per day
        elif t.startswith("mood_"):
            self.dedup_key = f"{t}:daily"
        # Fallback
        else:
            self.dedup_key = t

        return self.dedup_key

    @property
    def urgency_hint(self) -> int:
        """Default urgency 1-10 based on signal type. Brain can override."""
        high = {
            SignalType.CALENDAR_EVENT_APPROACHING,
            SignalType.CANVAS_OVERDUE,
            SignalType.CANVAS_DEADLINE_APPROACHING,
            SignalType.EMAIL_IMPORTANT_RECEIVED,
        }
        medium = {
            SignalType.CALENDAR_GAP_DETECTED,
            SignalType.CALENDAR_BUSY_DAY,
            SignalType.CALENDAR_EMPTY_DAY,
            SignalType.TASK_OVERDUE,
            SignalType.TASK_DUE_TODAY,
            SignalType.MOOD_TREND_DOWN,
            SignalType.EMAIL_UNREAD_PILING,
            SignalType.HABIT_STREAK_AT_RISK,
            SignalType.MEMORY_RELEVANCE_WINDOW,
        }
        if self.type in high:
            return 8
        if self.type in medium:
            return 5
        return 3
