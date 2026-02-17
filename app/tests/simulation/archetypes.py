"""User archetypes — behavioral models for simulation testing.

Each archetype defines how a simulated student responds to proactive
messages: reply probability, delay, sentiment, and active hours.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SimReply:
    """A simulated user reply to a proactive message."""
    text: str
    sentiment: str  # positive | neutral | negative | explicit_stop


class Archetype(ABC):
    """Base class for simulated user personas."""

    name: str = "base"
    wake_time: str = "08:00"
    sleep_time: str = "23:00"
    timezone: str = "Asia/Singapore"

    # Days since "account creation" at sim start (affects trust level)
    initial_days_active: int = 0
    initial_message_count: int = 0

    @abstractmethod
    def reply_probability(self, category: str, hour: int, day: int) -> float:
        """Probability [0,1] that user replies to a message of this category at this hour/day."""

    def reply_delay_minutes(self, category: str) -> int:
        """Minutes until user replies (if they decide to reply)."""
        return 10

    def reply_sentiment(self, category: str, day: int) -> str:
        """What sentiment the reply will have: positive|neutral|negative|explicit_stop."""
        return "neutral"

    def reply_text(self, category: str, sentiment: str) -> str:
        """Generate a realistic reply text."""
        if sentiment == "positive":
            return random.choice(["thanks!", "got it 👍", "helpful, ty", "nice, thanks"])
        if sentiment == "negative":
            return random.choice(["not helpful", "i know already", "annoying"])
        if sentiment == "explicit_stop":
            return f"stop sending me {category} messages"
        return random.choice(["ok", "sure", "k", "alright"])

    def simulate_reply(
        self, category: str, hour: int, day: int, rng: random.Random
    ) -> SimReply | None:
        """Decide whether/how to reply. Returns None if no reply."""
        prob = self.reply_probability(category, hour, day)
        if rng.random() > prob:
            return None
        sentiment = self.reply_sentiment(category, day)
        text = self.reply_text(category, sentiment)
        return SimReply(text=text, sentiment=sentiment)

    def mood_score(self, day: int) -> int:
        """Mood score 1-10 for a given simulation day."""
        return 6

    def is_active_hour(self, hour: int) -> bool:
        """Whether user is typically awake at this hour."""
        wake = int(self.wake_time.split(":")[0])
        sleep = int(self.sleep_time.split(":")[0])
        if sleep > wake:
            return wake <= hour < sleep
        return hour >= wake or hour < sleep


# ── Concrete archetypes ──────────────────────────────────────────────────────


class Diligent(Archetype):
    """High-performing student. Replies fast, engages with most categories."""
    name = "diligent"
    initial_days_active = 45
    initial_message_count = 150

    def reply_probability(self, category, hour, day):
        if not self.is_active_hour(hour):
            return 0.05
        base = {"deadline_warning": 0.9, "schedule_info": 0.85, "task_reminder": 0.8,
                "habit": 0.75, "wellbeing": 0.5, "briefing": 0.8, "grade_alert": 0.95,
                "email_alert": 0.7, "memory_recall": 0.4, "nudge": 0.6}
        return base.get(category, 0.6)

    def reply_delay_minutes(self, category):
        return random.randint(2, 8)

    def reply_sentiment(self, category, day):
        return random.choice(["positive", "positive", "neutral"])


class Procrastinator(Archetype):
    """Ignores early reminders but engages when deadline is close."""
    name = "procrastinator"
    initial_days_active = 30
    initial_message_count = 80

    def reply_probability(self, category, hour, day):
        if not self.is_active_hour(hour):
            return 0.05
        if category in ("deadline_warning", "task_reminder"):
            return 0.15  # ignores early — world.py sends with hours_before_due
        if category == "wellbeing":
            return 0.05
        return 0.3

    def reply_delay_minutes(self, category):
        return random.randint(15, 45)

    def reply_sentiment(self, category, day):
        return "neutral"


class Disengaging(Archetype):
    """Starts engaged, gradually stops replying over the simulation."""
    name = "disengaging"
    initial_days_active = 60
    initial_message_count = 200

    def reply_probability(self, category, hour, day):
        if not self.is_active_hour(hour):
            return 0.02
        base = 0.7 - (day * 0.02)  # drops ~2% per day
        return max(0.05, base)

    def reply_delay_minutes(self, category):
        return random.randint(10, 30)

    def reply_sentiment(self, category, day):
        if day > 20:
            return random.choice(["neutral", "negative"])
        return "neutral"


class NightOwl(Archetype):
    """Only active 10pm–3am. Sleeps through morning."""
    name = "nightowl"
    wake_time = "14:00"
    sleep_time = "04:00"
    initial_days_active = 40
    initial_message_count = 120

    def reply_probability(self, category, hour, day):
        # Active 10pm to 4am (peak), sluggish 2pm-10pm
        if 22 <= hour or hour < 4:
            return 0.85
        if 14 <= hour < 22:
            return 0.3
        return 0.05  # 4am-2pm: asleep

    def reply_delay_minutes(self, category):
        return random.randint(3, 10)

    def reply_sentiment(self, category, day):
        return random.choice(["positive", "neutral"])


class Overwhelmed(Archetype):
    """Stressed student. Low mood, slow responder, engages with wellbeing."""
    name = "overwhelmed"
    initial_days_active = 50
    initial_message_count = 100

    def reply_probability(self, category, hour, day):
        if not self.is_active_hour(hour):
            return 0.03
        if category == "wellbeing":
            return 0.65
        if category in ("deadline_warning", "task_reminder"):
            return 0.35
        return 0.2

    def reply_delay_minutes(self, category):
        return random.randint(30, 70)

    def reply_sentiment(self, category, day):
        if category == "wellbeing":
            return "positive"
        return "neutral"

    def mood_score(self, day):
        # Starts at 5, dips to 3 around day 10, slowly recovers
        import math
        return max(2, min(7, int(5 - 2 * math.sin(day * 0.15) + day * 0.05)))


class PowerUser(Archetype):
    """Engages with everything, gives positive and meta-feedback."""
    name = "poweruser"
    initial_days_active = 90
    initial_message_count = 400

    def reply_probability(self, category, hour, day):
        if not self.is_active_hour(hour):
            return 0.1
        return 0.95

    def reply_delay_minutes(self, category):
        return random.randint(1, 5)

    def reply_sentiment(self, category, day):
        return "positive"

    def reply_text(self, category, sentiment):
        # Occasionally gives meta-feedback
        if random.random() < 0.1:
            return random.choice([
                "the buttons are really useful",
                "these deadline reminders are great",
                "love the morning briefings",
            ])
        return super().reply_text(category, sentiment)


class Hostile(Archetype):
    """Annoyed user. Sends negative replies and explicit stops."""
    name = "hostile"
    initial_days_active = 20
    initial_message_count = 30
    _stop_sent: dict = field(default_factory=dict) if False else {}

    def __init__(self):
        self._category_count: dict[str, int] = {}  # track sends per category
        self._stopped_categories: set[str] = set()

    def reply_probability(self, category, hour, day):
        if not self.is_active_hour(hour):
            return 0.05
        if category in self._stopped_categories:
            return 0.0  # shouldn't even receive these
        return 0.25

    def reply_delay_minutes(self, category):
        return random.randint(5, 15)

    def reply_sentiment(self, category, day):
        count = self._category_count.get(category, 0)
        self._category_count[category] = count + 1
        if count >= 2 and category not in self._stopped_categories:
            self._stopped_categories.add(category)
            return "explicit_stop"
        return "negative"

    def reply_text(self, category, sentiment):
        if sentiment == "explicit_stop":
            return f"stop sending me {category} messages please"
        return random.choice(["not helpful", "I don't need this", "stop"])


class NewUser(Archetype):
    """Fresh onboarding, no history. Slowly warms up."""
    name = "newuser"
    initial_days_active = 0
    initial_message_count = 0

    def reply_probability(self, category, hour, day):
        if not self.is_active_hour(hour):
            return 0.05
        if day < 3:
            return 0.4  # cautious first few days
        if day < 7:
            return 0.55
        return 0.7  # warms up

    def reply_delay_minutes(self, category):
        return random.randint(5, 20)

    def reply_sentiment(self, category, day):
        if day < 3:
            return "neutral"
        return random.choice(["positive", "neutral"])


ALL_ARCHETYPES: list[type[Archetype]] = [
    Diligent, Procrastinator, Disengaging, NightOwl,
    Overwhelmed, PowerUser, Hostile, NewUser,
]

# Signal type → proactive category mapping (used by sim_runner)
SIGNAL_TO_CATEGORY: dict[str, str] = {
    "calendar_event_approaching": "schedule_info",
    "calendar_event_started": "schedule_info",
    "calendar_gap_detected": "schedule_info",
    "calendar_busy_day": "briefing",
    "calendar_empty_day": "schedule_info",
    "canvas_deadline_approaching": "deadline_warning",
    "canvas_overdue": "deadline_warning",
    "canvas_grade_posted": "grade_alert",
    "email_unread_piling": "email_alert",
    "email_important_received": "email_alert",
    "time_morning_window": "briefing",
    "time_evening_window": "wellbeing",
    "time_since_last_interaction": "nudge",
    "mood_trend_down": "wellbeing",
    "mood_trend_up": "wellbeing",
    "task_overdue": "task_reminder",
    "task_due_today": "task_reminder",
    "memory_relevance_window": "memory_recall",
    "habit_streak_at_risk": "habit",
    "habit_streak_milestone": "habit",
}
