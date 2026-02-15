"""Tests for donna.brain.rules — scoring and filtering logic."""

import unittest.mock as mock
from datetime import datetime, timezone

import pytest
from donna.brain.rules import (
    COOLDOWN_MINUTES,
    SCORE_THRESHOLD,
    URGENT_SCORE_OVERRIDE,
    W_RELEVANCE,
    W_TIMING,
    W_URGENCY,
    score_and_filter,
)


def _patch_local_hour(hour: int):
    """Context manager that patches _get_local_hour to return a fixed hour."""
    return mock.patch("donna.brain.rules._get_local_hour", return_value=hour)


def _ctx(wake="08:00", sleep="23:00", minutes_since=60, tz="UTC", sent_today=0, conversation=None):
    ctx = {
        "user": {
            "wake_time": wake,
            "sleep_time": sleep,
            "timezone": tz,
        },
        "minutes_since_last_message": minutes_since,
        "proactive_sent_today": sent_today,
    }
    if conversation is not None:
        ctx["recent_conversation"] = conversation
    return ctx


def _candidate(msg="test", relevance=7, timing=7, urgency=7, category="nudge"):
    return {
        "message": msg,
        "relevance": relevance,
        "timing": timing,
        "urgency": urgency,
        "trigger_signals": [],
        "category": category,
    }


class TestScoreCalculation:
    def test_composite_formula(self):
        cands = [_candidate(relevance=8, timing=7, urgency=6)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx())
        expected = 8 * W_RELEVANCE + 7 * W_TIMING + 6 * W_URGENCY
        assert len(result) == 1
        assert result[0]["composite_score"] == pytest.approx(expected, abs=0.01)

    def test_perfect_score(self):
        cands = [_candidate(relevance=10, timing=10, urgency=10)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx())
        assert result[0]["composite_score"] == pytest.approx(10.0, abs=0.01)

    def test_minimum_score(self):
        cands = [_candidate(relevance=1, timing=1, urgency=1)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 0


class TestScoreThreshold:
    def test_low_score_filtered(self):
        cands = [_candidate(relevance=3, timing=3, urgency=2)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 0

    def test_borderline_passes(self):
        # 6*0.4 + 6*0.35 + 5*0.25 = 2.4 + 2.1 + 1.25 = 5.75 > 5.5
        cands = [_candidate(relevance=6, timing=6, urgency=5)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 1


class TestSorting:
    def test_sorted_by_score_descending(self):
        cands = [
            _candidate(msg="low", relevance=6, timing=6, urgency=6),
            _candidate(msg="high", relevance=9, timing=9, urgency=9),
            _candidate(msg="mid", relevance=7, timing=7, urgency=7),
        ]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 3
        assert result[0]["message"] == "high"
        assert result[1]["message"] == "mid"
        assert result[2]["message"] == "low"


class TestQuietHours:
    def test_quiet_hours_blocks_normal(self):
        """At 2am (sleep=23, wake=8), medium score should be blocked."""
        cands = [_candidate(relevance=7, timing=7, urgency=7)]
        with _patch_local_hour(2):
            result = score_and_filter(cands, _ctx(wake="08:00", sleep="23:00"))
        assert len(result) == 0

    def test_quiet_hours_allows_urgent(self):
        """Score > 8.5 should bypass quiet hours."""
        cands = [_candidate(relevance=10, timing=9, urgency=9)]
        with _patch_local_hour(2):
            result = score_and_filter(cands, _ctx(wake="08:00", sleep="23:00"))
        # Composite = 10*0.4 + 9*0.35 + 9*0.25 = 9.4 > 8.5
        assert len(result) == 1

    def test_daytime_not_quiet(self):
        """At 2pm (between wake=8 and sleep=23), all scores should pass quiet hours."""
        cands = [_candidate(relevance=7, timing=7, urgency=7)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 1

    def test_timezone_conversion(self):
        """User in Asia/Singapore should use SGT hour, not UTC."""
        cands = [_candidate(relevance=7, timing=7, urgency=7)]
        # Mock _get_local_hour to return 14 (2pm SGT) — should be daytime
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx(tz="Asia/Singapore"))
        assert len(result) == 1


class TestCooldown:
    def test_cooldown_blocks_rapid_fire(self):
        cands = [_candidate(relevance=7, timing=7, urgency=7)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx(minutes_since=10))
        assert len(result) == 0

    def test_cooldown_passed(self):
        cands = [_candidate(relevance=7, timing=7, urgency=7)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx(minutes_since=45))
        assert len(result) == 1

    def test_urgent_bypasses_cooldown(self):
        cands = [_candidate(relevance=10, timing=9, urgency=9)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx(minutes_since=5))
        assert len(result) == 1

    def test_no_previous_message_passes(self):
        cands = [_candidate(relevance=7, timing=7, urgency=7)]
        ctx = _ctx()
        ctx["minutes_since_last_message"] = None
        with _patch_local_hour(14):
            result = score_and_filter(cands, ctx)
        assert len(result) == 1


class TestDailyCap:
    def test_daily_cap_blocks_excess(self):
        """5th message of the day should be blocked (cap is 4)."""
        cands = [_candidate(relevance=8, timing=8, urgency=8)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx(sent_today=4))
        assert len(result) == 0

    def test_daily_cap_allows_under_limit(self):
        cands = [_candidate(relevance=8, timing=8, urgency=8)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx(sent_today=2))
        assert len(result) == 1


class TestDedup:
    def test_dedup_blocks_repeat(self):
        """If Donna said something very similar recently, filter it."""
        conversation = [
            {"role": "assistant", "content": "SE assignment due Friday at midnight", "time": ""},
        ]
        cands = [_candidate(msg="SE assignment due Friday at midnight")]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx(conversation=conversation))
        assert len(result) == 0

    def test_dedup_allows_different_message(self):
        conversation = [
            {"role": "assistant", "content": "SE assignment due Friday at midnight", "time": ""},
        ]
        cands = [_candidate(msg="You have a 3-hour gap after lunch tomorrow")]
        with _patch_local_hour(14):
            result = score_and_filter(cands, _ctx(conversation=conversation))
        assert len(result) == 1


class TestEmptyInput:
    def test_empty_candidates(self):
        assert score_and_filter([], _ctx()) == []

    def test_none_user_context(self):
        cands = [_candidate(relevance=7, timing=7, urgency=7)]
        with _patch_local_hour(14):
            result = score_and_filter(cands, {"minutes_since_last_message": 60})
        assert isinstance(result, list)
