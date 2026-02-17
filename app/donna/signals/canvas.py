"""Canvas signal collector — checks assignments and deadlines."""

import logging
from datetime import datetime, timezone

from donna.signals.base import Signal, SignalType
from tools.canvas import get_canvas_assignments, get_canvas_grades

logger = logging.getLogger(__name__)

# Deadline thresholds in hours
_DEADLINE_THRESHOLDS = [
    (3, "3_hours"),
    (12, "12_hours"),
    (24, "1_day"),
    (48, "2_days"),
    (72, "3_days"),
]


async def collect_canvas_signals(user_id: str) -> list[Signal]:
    """Generate signals from Canvas assignments."""
    now = datetime.now(timezone.utc)
    signals: list[Signal] = []

    # Fetch assignments due in next 14 days (wide window for context)
    assignments = await get_canvas_assignments(user_id=user_id, days_ahead=14)

    if assignments and isinstance(assignments[0], dict) and "error" in assignments[0]:
        return []

    for assignment in assignments:
        due_str = assignment.get("due_date")
        if not due_str:
            continue

        try:
            due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        hours_until = (due_dt - now).total_seconds() / 3600
        submitted = assignment.get("submitted", False)

        # ── Overdue and not submitted ────────────────────────────────
        if hours_until < 0 and not submitted:
            signals.append(Signal(
                type=SignalType.CANVAS_OVERDUE,
                user_id=user_id,
                data={
                    "title": assignment.get("title", ""),
                    "course": assignment.get("course", ""),
                    "due_date": due_str,
                    "hours_overdue": round(abs(hours_until), 1),
                    "points": assignment.get("points"),
                },
                source="canvas",
            ))
            continue

        # ── Approaching deadline (not submitted) ─────────────────────
        if not submitted and hours_until > 0:
            for threshold_hours, label in _DEADLINE_THRESHOLDS:
                if hours_until <= threshold_hours:
                    signals.append(Signal(
                        type=SignalType.CANVAS_DEADLINE_APPROACHING,
                        user_id=user_id,
                        data={
                            "title": assignment.get("title", ""),
                            "course": assignment.get("course", ""),
                            "due_date": due_str,
                            "hours_until": round(hours_until, 1),
                            "urgency_label": label,
                            "points": assignment.get("points"),
                        },
                        source="canvas",
                    ))
                    break  # only emit the tightest threshold

    # ── Recently graded assignments ──────────────────────────────
    try:
        grades = await get_canvas_grades(user_id=user_id)
        if grades and not (isinstance(grades[0], dict) and "error" in grades[0]):
            for grade in grades:
                if grade.get("score") is not None:
                    # Build a meaningful title for dedup — fall back to
                    # course+score so different grades don't collapse to
                    # the same dedup key.
                    title = grade.get("assignment") or ""
                    if not title or title == "Unknown":
                        course = grade.get("course", "")
                        score = grade.get("score", "")
                        title = f"{course}:{score}" if course else f"grade:{score}"
                    signals.append(Signal(
                        type=SignalType.CANVAS_GRADE_POSTED,
                        user_id=user_id,
                        data={
                            "title": title,
                            "course": grade.get("course", ""),
                            "score": grade.get("score"),
                            "points_possible": grade.get("points_possible"),
                        },
                        source="canvas",
                    ))
    except Exception:
        logger.exception("Failed to fetch Canvas grades for user %s", user_id)

    return signals
