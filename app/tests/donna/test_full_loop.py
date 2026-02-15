"""End-to-end scenario tests for the Donna proactive loop.

These test the full pipeline: signals → context → candidates → score → send,
using the test SQLite DB and mocked LLM + WhatsApp.
"""

import json
import unittest.mock as mock
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from donna.brain.rules import COOLDOWN_MINUTES, MAX_PROACTIVE_PER_DAY
from donna.loop import donna_loop
from donna.signals.base import Signal, SignalType
from tests.conftest import (
    make_chat_message,
    make_memory_fact,
    make_mood,
    make_task,
    make_user,
)


def _patch_daytime(hour=14):
    """Patch _get_local_hour and datetime.now to simulate daytime."""
    return mock.patch("donna.brain.rules._get_local_hour", return_value=hour)


def _mock_llm_response(candidates: list[dict]):
    """Create a mock LLM that returns the given candidates as JSON."""
    mock_resp = AsyncMock()
    mock_resp.content = json.dumps(candidates)
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = mock_resp
    return mock_llm


class TestDonnaScenarios:

    async def test_scenario_deadline_approaching(self, db_session, patch_async_session):
        """Deadline + calendar gap → Donna suggests using free time."""
        user = make_user(id="s-deadline")
        task = make_task(
            user_id="s-deadline", title="SE assignment",
            due_date=datetime(2025, 6, 16, 23, 59),
            source="canvas",
        )
        db_session.add_all([user, task])
        await db_session.commit()

        candidates = [{
            "message": "SE due tomorrow midnight. You've got a 3-hour gap after 2pm — want me to block it?",
            "relevance": 9, "timing": 8, "urgency": 7,
            "trigger_signals": ["canvas_deadline_approaching", "calendar_gap_detected"],
            "category": "deadline_warning",
        }]

        with (
            patch("donna.signals.collector.collect_calendar_signals", return_value=[
                Signal(type=SignalType.CALENDAR_GAP_DETECTED, user_id="s-deadline",
                       data={"start": "14:00", "end": "17:00", "duration_hours": 3}),
            ]),
            patch("donna.signals.collector.collect_canvas_signals", return_value=[
                Signal(type=SignalType.CANVAS_DEADLINE_APPROACHING, user_id="s-deadline",
                       data={"title": "SE assignment", "hours_until_due": 18}),
            ]),
            patch("donna.signals.collector.collect_email_signals", return_value=[]),
            patch("donna.brain.candidates.llm", _mock_llm_response(candidates)),
            patch("donna.memory.recall.llm", _mock_llm_response([])),
            _patch_daytime(14),
            patch("donna.brain.sender.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        ):
            sent = await donna_loop("s-deadline")

        assert sent == 1
        mock_wa.assert_called_once()
        assert "SE" in mock_wa.call_args.kwargs.get("text", mock_wa.call_args[1].get("text", ""))

    async def test_scenario_nothing_happening(self, db_session, patch_async_session):
        """No signals → donna_loop returns 0, no messages sent."""
        user = make_user(id="s-quiet")
        db_session.add(user)
        await db_session.commit()

        with (
            patch("donna.signals.collector.collect_calendar_signals", return_value=[]),
            patch("donna.signals.collector.collect_canvas_signals", return_value=[]),
            patch("donna.signals.collector.collect_email_signals", return_value=[]),
            patch("donna.signals.collector.collect_internal_signals", return_value=[]),
            patch("donna.brain.sender.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        ):
            sent = await donna_loop("s-quiet")

        assert sent == 0
        mock_wa.assert_not_called()

    async def test_scenario_memory_recall_restaurant(self, db_session, patch_async_session):
        """Old restaurant memory + Friday evening + empty calendar → surfaces memory."""
        user = make_user(id="s-memory")
        fact = make_memory_fact(
            user_id="s-memory",
            fact="chimichanga: new restaurant near campus, looks fire",
            category="entity:place",
            created_at=datetime(2025, 6, 1, 12, 0),
        )
        db_session.add_all([user, fact])
        await db_session.commit()

        candidates = [{
            "message": "Free tonight — wasn't there that chimichanga place you wanted to try?",
            "relevance": 7, "timing": 8, "urgency": 3,
            "trigger_signals": ["calendar_empty_day", "memory_relevance_window"],
            "category": "memory_recall",
        }]

        # Mock the recall LLM to return queries that match our fact
        recall_resp = AsyncMock()
        recall_resp.content = json.dumps(["chimichanga", "restaurant", "campus"])
        recall_llm = AsyncMock()
        recall_llm.ainvoke.return_value = recall_resp

        with (
            patch("donna.signals.collector.collect_calendar_signals", return_value=[
                Signal(type=SignalType.CALENDAR_EMPTY_DAY, user_id="s-memory", data={}),
            ]),
            patch("donna.signals.collector.collect_canvas_signals", return_value=[]),
            patch("donna.signals.collector.collect_email_signals", return_value=[]),
            patch("donna.brain.candidates.llm", _mock_llm_response(candidates)),
            patch("donna.memory.recall.llm", recall_llm),
            _patch_daytime(19),
            patch("donna.brain.sender.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        ):
            sent = await donna_loop("s-memory")

        assert sent == 1
        assert "chimichanga" in mock_wa.call_args.kwargs.get(
            "text", mock_wa.call_args[1].get("text", "")
        ).lower()

    async def test_scenario_mood_low_gentle_tone(self, db_session, patch_async_session):
        """Low mood + overdue tasks → Donna mentions tasks gently."""
        user = make_user(id="s-mood")
        for score in [3, 2, 4, 7, 6, 8]:
            db_session.add(make_mood(user_id="s-mood", score=score))
        task = make_task(
            user_id="s-mood", title="Readings ch 5",
            due_date=datetime(2025, 6, 14, 12, 0),
        )
        db_session.add_all([user, task])
        await db_session.commit()

        candidates = [{
            "message": "Whenever you're ready — those ch 5 readings are still there. No rush.",
            "relevance": 6, "timing": 7, "urgency": 5,
            "trigger_signals": ["task_overdue", "mood_trend_down"],
            "category": "task_reminder",
        }]

        with (
            patch("donna.signals.collector.collect_calendar_signals", return_value=[]),
            patch("donna.signals.collector.collect_canvas_signals", return_value=[]),
            patch("donna.signals.collector.collect_email_signals", return_value=[]),
            patch("donna.brain.candidates.llm", _mock_llm_response(candidates)),
            patch("donna.memory.recall.llm", _mock_llm_response([])),
            _patch_daytime(14),
            patch("donna.brain.sender.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        ):
            sent = await donna_loop("s-mood")

        assert sent == 1

    async def test_scenario_quiet_hours_blocks(self, db_session, patch_async_session):
        """2am + medium urgency → message blocked."""
        user = make_user(id="s-quiet-hr")
        db_session.add(user)
        await db_session.commit()

        candidates = [{
            "message": "Canvas deadline in 3 days",
            "relevance": 6, "timing": 5, "urgency": 4,
            "trigger_signals": ["canvas_deadline_approaching"],
            "category": "deadline_warning",
        }]

        with (
            patch("donna.signals.collector.collect_calendar_signals", return_value=[]),
            patch("donna.signals.collector.collect_canvas_signals", return_value=[
                Signal(type=SignalType.CANVAS_DEADLINE_APPROACHING, user_id="s-quiet-hr",
                       data={"hours_until_due": 72}),
            ]),
            patch("donna.signals.collector.collect_email_signals", return_value=[]),
            patch("donna.brain.candidates.llm", _mock_llm_response(candidates)),
            patch("donna.memory.recall.llm", _mock_llm_response([])),
            _patch_daytime(2),  # 2am — quiet hours
            patch("donna.brain.sender.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        ):
            sent = await donna_loop("s-quiet-hr")

        assert sent == 0
        mock_wa.assert_not_called()

    async def test_scenario_urgent_overrides_quiet(self, db_session, patch_async_session):
        """2am + assignment due in 1 hour → high urgency overrides quiet hours."""
        user = make_user(id="s-urgent")
        db_session.add(user)
        await db_session.commit()

        candidates = [{
            "message": "Your assignment is due in 1 HOUR!",
            "relevance": 10, "timing": 10, "urgency": 10,
            "trigger_signals": ["canvas_deadline_approaching"],
            "category": "deadline_warning",
        }]

        with (
            patch("donna.signals.collector.collect_calendar_signals", return_value=[]),
            patch("donna.signals.collector.collect_canvas_signals", return_value=[
                Signal(type=SignalType.CANVAS_DEADLINE_APPROACHING, user_id="s-urgent",
                       data={"hours_until_due": 1}),
            ]),
            patch("donna.signals.collector.collect_email_signals", return_value=[]),
            patch("donna.brain.candidates.llm", _mock_llm_response(candidates)),
            patch("donna.memory.recall.llm", _mock_llm_response([])),
            _patch_daytime(2),  # 2am — quiet hours, but score will be 10.0 > 8.5
            patch("donna.brain.sender.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        ):
            sent = await donna_loop("s-urgent")

        assert sent == 1
        mock_wa.assert_called_once()

    async def test_scenario_cooldown_respected(self, db_session, patch_async_session):
        """Donna sent a message 15 min ago → new non-urgent message held."""
        user = make_user(id="s-cooldown")
        # Recent assistant message 15 min ago
        recent_msg = make_chat_message(
            user_id="s-cooldown", role="assistant",
            content="SE due Friday",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=15),
        )
        db_session.add_all([user, recent_msg])
        await db_session.commit()

        candidates = [{
            "message": "Don't forget to hydrate",
            "relevance": 5, "timing": 6, "urgency": 3,
            "trigger_signals": ["time_since_last_interaction"],
            "category": "wellbeing",
        }]

        with (
            patch("donna.signals.collector.collect_calendar_signals", return_value=[]),
            patch("donna.signals.collector.collect_canvas_signals", return_value=[]),
            patch("donna.signals.collector.collect_email_signals", return_value=[]),
            patch("donna.brain.candidates.llm", _mock_llm_response(candidates)),
            patch("donna.memory.recall.llm", _mock_llm_response([])),
            _patch_daytime(14),
            patch("donna.brain.sender.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        ):
            sent = await donna_loop("s-cooldown")

        assert sent == 0
        mock_wa.assert_not_called()

    async def test_scenario_busy_day_briefing(self, db_session, patch_async_session):
        """Morning window + 6 events → morning briefing sent."""
        user = make_user(id="s-busy")
        db_session.add(user)
        await db_session.commit()

        candidates = [{
            "message": "Packed day — 6 things on your calendar. First up at 9am.",
            "relevance": 8, "timing": 9, "urgency": 6,
            "trigger_signals": ["calendar_busy_day", "time_morning_window"],
            "category": "briefing",
        }]

        with (
            patch("donna.signals.collector.collect_calendar_signals", return_value=[
                Signal(type=SignalType.CALENDAR_BUSY_DAY, user_id="s-busy",
                       data={"event_count": 6}),
            ]),
            patch("donna.signals.collector.collect_canvas_signals", return_value=[]),
            patch("donna.signals.collector.collect_email_signals", return_value=[]),
            patch("donna.brain.candidates.llm", _mock_llm_response(candidates)),
            patch("donna.memory.recall.llm", _mock_llm_response([])),
            _patch_daytime(8),
            patch("donna.brain.sender.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        ):
            sent = await donna_loop("s-busy")

        assert sent == 1
        mock_wa.assert_called_once()
