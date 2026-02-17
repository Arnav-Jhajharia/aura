"""Cross-signal enrichment — derives compound insights from multiple signals."""

import logging

from donna.signals.base import Signal, SignalType

logger = logging.getLogger(__name__)


def enrich_signals(signals: list[Signal]) -> list[Signal]:
    """Annotate and augment signals based on cross-signal patterns.

    Runs synchronously and in-memory; no DB or network calls.
    Returns the original signals plus any new synthetic ones.
    """
    if not signals:
        return signals

    types = {s.type for s in signals}
    by_type: dict[SignalType, list[Signal]] = {}
    for s in signals:
        by_type.setdefault(s.type, []).append(s)

    # ── Pattern 1: Calendar gap + Canvas deadline → study suggestion ──
    gaps = by_type.get(SignalType.CALENDAR_GAP_DETECTED, [])
    deadlines = by_type.get(SignalType.CANVAS_DEADLINE_APPROACHING, [])

    if gaps and deadlines:
        # Pick the most urgent deadline
        closest = min(deadlines, key=lambda s: s.data.get("hours_until", 999))
        # Pick the longest gap
        best_gap = max(gaps, key=lambda s: s.data.get("duration_hours", 0))
        best_gap.data["suggested_task"] = closest.data.get("title", "")
        best_gap.data["suggested_course"] = closest.data.get("course", "")
        logger.debug(
            "Enrichment: gap %s annotated with deadline '%s'",
            best_gap.data.get("start"), closest.data.get("title"),
        )

    # ── Pattern 2: Mood down + busy day → care escalation ────────────
    if SignalType.MOOD_TREND_DOWN in types and SignalType.CALENDAR_BUSY_DAY in types:
        for mood_sig in by_type[SignalType.MOOD_TREND_DOWN]:
            mood_sig.data["care_escalation"] = True
        logger.debug("Enrichment: mood-down + busy-day → care escalation")

    # ── Pattern 3: Habit at risk + evening window → bedtime reminder ──
    if SignalType.HABIT_STREAK_AT_RISK in types and SignalType.TIME_EVENING_WINDOW in types:
        for habit_sig in by_type[SignalType.HABIT_STREAK_AT_RISK]:
            habit_sig.data["bedtime_reminder"] = True
        logger.debug("Enrichment: habit-at-risk + evening → bedtime reminder hint")

    # ── Pattern 4: Task due today + calendar gap → scheduling hint ────
    tasks_due = by_type.get(SignalType.TASK_DUE_TODAY, [])
    if tasks_due and gaps:
        best_gap = max(gaps, key=lambda s: s.data.get("duration_hours", 0))
        for task_sig in tasks_due:
            task_sig.data["scheduling_hint"] = {
                "gap_start": best_gap.data.get("start", ""),
                "gap_end": best_gap.data.get("end", ""),
                "gap_hours": best_gap.data.get("duration_hours", 0),
            }
        logger.debug("Enrichment: task-due-today + gap → scheduling hint")

    return signals
