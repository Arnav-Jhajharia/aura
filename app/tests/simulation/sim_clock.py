"""SimClock — controllable time for simulation tests.

Provides a clock that can be advanced in discrete steps, plus context
managers that monkey-patch datetime.now() across Donna modules.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class SimClock:
    """A controllable clock for simulation time."""

    def __init__(self, start: datetime | None = None):
        self._current = start or datetime(2026, 1, 12, 8, 0, tzinfo=timezone.utc)

    def now(self, tz=None) -> datetime:
        if tz is None:
            return self._current.replace(tzinfo=None)
        return self._current.astimezone(tz)

    def advance(self, hours: int = 0, minutes: int = 0) -> datetime:
        self._current += timedelta(hours=hours, minutes=minutes)
        return self._current

    @property
    def current(self) -> datetime:
        return self._current

    @property
    def current_naive(self) -> datetime:
        return self._current.replace(tzinfo=None)

    @property
    def hour(self) -> int:
        return self._current.hour

    @property
    def date(self):
        return self._current.date()


def _make_patched_now(clock: SimClock):
    """Create a datetime.now replacement that returns SimClock time."""
    _original_now = datetime.now

    def _patched_now(tz=None):
        if tz is None:
            return clock.current_naive
        if isinstance(tz, str):
            tz = zoneinfo.ZoneInfo(tz)
        return clock.current.astimezone(tz)

    return _patched_now


# Modules that call datetime.now() and need patching
_DATETIME_MODULES = [
    "donna.loop",
    "donna.signals.base",
    "donna.signals.internal",
    "donna.signals.dedup",
    "donna.signals.collector",
    "donna.brain.prefilter",
    "donna.brain.context",
    "donna.brain.rules",
    "donna.brain.sender",
    "donna.brain.feedback",
    "donna.brain.feedback_metrics",
    "donna.brain.trust",
    "donna.brain.behaviors",
    "donna.reflection",
    "donna.user_model",
    "donna.memory.entities",
    "donna.memory.recall",
    "agent.scheduler",
]


class SimTimeContext:
    """Context manager that patches datetime.now across all Donna modules."""

    def __init__(self, clock: SimClock):
        self.clock = clock
        self._patches = []

    def __enter__(self):
        patched = _make_patched_now(self.clock)
        for mod in _DATETIME_MODULES:
            try:
                p = patch(f"{mod}.datetime")
                mock_dt = p.start()
                mock_dt.now = patched
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                mock_dt.utcnow = lambda: self.clock.current_naive
                # Preserve timedelta, timezone, etc.
                mock_dt.timedelta = timedelta
                mock_dt.timezone = timezone
                self._patches.append(p)
            except (AttributeError, ModuleNotFoundError):
                pass

        # Also patch _get_local_hour in prefilter
        p2 = patch(
            "donna.brain.prefilter._get_local_hour",
            side_effect=lambda user_tz="UTC": self.clock.now(
                zoneinfo.ZoneInfo(user_tz) if user_tz != "UTC" else timezone.utc
            ).hour,
        )
        p2.start()
        self._patches.append(p2)
        return self

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()
        self._patches.clear()
