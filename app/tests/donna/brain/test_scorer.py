"""Tests for donna.brain.rules — scoring, threshold, and dedup logic.

Hard rules (quiet hours, cooldown, daily cap) are tested in test_prefilter.py.
"""

from unittest.mock import patch

import pytest
from donna.brain.rules import (
    DEFERRED_MIN_SCORE,
    W_RELEVANCE,
    W_TIMING,
    W_URGENCY,
    score_and_filter,
)


def _ctx(conversation=None, score_threshold=None):
    ctx = {}
    if conversation is not None:
        ctx["recent_conversation"] = conversation
    if score_threshold is not None:
        ctx["score_threshold"] = score_threshold
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
        result = score_and_filter(cands, _ctx())
        expected = 8 * W_RELEVANCE + 7 * W_TIMING + 6 * W_URGENCY
        assert len(result) == 1
        assert result[0]["composite_score"] == pytest.approx(expected, abs=0.01)

    def test_perfect_score(self):
        cands = [_candidate(relevance=10, timing=10, urgency=10)]
        result = score_and_filter(cands, _ctx())
        assert result[0]["composite_score"] == pytest.approx(10.0, abs=0.01)

    def test_minimum_score(self):
        cands = [_candidate(relevance=1, timing=1, urgency=1)]
        result = score_and_filter(cands, _ctx())
        assert len(result) == 0


class TestScoreThreshold:
    def test_low_score_filtered(self):
        cands = [_candidate(relevance=3, timing=3, urgency=2)]
        result = score_and_filter(cands, _ctx())
        assert len(result) == 0

    def test_borderline_passes(self):
        # 6*0.4 + 6*0.35 + 5*0.25 = 2.4 + 2.1 + 1.25 = 5.75 > 5.5
        cands = [_candidate(relevance=6, timing=6, urgency=5)]
        result = score_and_filter(cands, _ctx())
        assert len(result) == 1

    def test_custom_threshold(self):
        """Trust-dependent threshold from context."""
        cands = [_candidate(relevance=7, timing=7, urgency=7)]  # composite = 7.0
        # With threshold 7.5, should be filtered
        result = score_and_filter(cands, _ctx(score_threshold=7.5))
        assert len(result) == 0
        # With threshold 6.0, should pass
        result2 = score_and_filter(
            [_candidate(relevance=7, timing=7, urgency=7)],
            _ctx(score_threshold=6.0),
        )
        assert len(result2) == 1


class TestSorting:
    def test_sorted_by_score_descending(self):
        cands = [
            _candidate(msg="low", relevance=6, timing=6, urgency=6),
            _candidate(msg="high", relevance=9, timing=9, urgency=9),
            _candidate(msg="mid", relevance=7, timing=7, urgency=7),
        ]
        result = score_and_filter(cands, _ctx())
        assert len(result) == 3
        assert result[0]["message"] == "high"
        assert result[1]["message"] == "mid"
        assert result[2]["message"] == "low"


class TestDedup:
    def test_dedup_blocks_repeat(self):
        conversation = [
            {"role": "assistant", "content": "SE assignment due Friday at midnight", "time": ""},
        ]
        cands = [_candidate(msg="SE assignment due Friday at midnight")]
        result = score_and_filter(cands, _ctx(conversation=conversation))
        assert len(result) == 0

    def test_dedup_allows_different_message(self):
        conversation = [
            {"role": "assistant", "content": "SE assignment due Friday at midnight", "time": ""},
        ]
        cands = [_candidate(msg="You have a 3-hour gap after lunch tomorrow")]
        result = score_and_filter(cands, _ctx(conversation=conversation))
        assert len(result) == 1


class TestSuppression:
    def test_suppressed_category_filtered(self):
        """Candidates in suppressed categories should be hard-filtered."""
        ctx = _ctx()
        ctx["category_suppression"] = {
            "suppressed": {"nudge": {"reason": "low engagement"}}
        }
        cands = [_candidate(msg="Go to the gym", relevance=9, timing=9, urgency=9, category="nudge")]
        result = score_and_filter(cands, ctx)
        assert len(result) == 0

    def test_non_suppressed_category_passes(self):
        """Candidates NOT in suppressed categories should pass normally."""
        ctx = _ctx()
        ctx["category_suppression"] = {
            "suppressed": {"nudge": {"reason": "low engagement"}}
        }
        cands = [_candidate(msg="CS2103 due tomorrow", relevance=9, timing=9, urgency=9, category="deadline_warning")]
        result = score_and_filter(cands, ctx)
        assert len(result) == 1

    def test_suppression_empty_dict(self):
        """Empty suppression dict should not filter anything."""
        ctx = _ctx()
        ctx["category_suppression"] = {"suppressed": {}}
        cands = [_candidate(relevance=7, timing=7, urgency=7, category="nudge")]
        result = score_and_filter(cands, ctx)
        assert len(result) == 1


class TestExploration:
    def test_exploration_allows_borderline(self):
        """With random seeded to always explore, borderline candidates should pass."""
        import random
        random.seed(0)  # seed that produces random() < 0.10 for the first call
        # We need to find a seed where random.random() < 0.10
        # Let's just mock it
        from unittest.mock import patch
        ctx = _ctx(score_threshold=6.0)
        # composite = 5*0.4 + 6*0.35 + 5*0.25 = 2.0 + 2.1 + 1.25 = 5.35
        # This is below 6.0 but >= 6.0 - 1.0 = 5.0
        cands = [_candidate(msg="explore this", relevance=5, timing=6, urgency=5, category="wellbeing")]
        with patch("donna.brain.rules.random.random", return_value=0.05):
            result = score_and_filter(cands, ctx)
        assert len(result) == 1
        assert result[0].get("_explored") is True

    def test_no_exploration_when_random_high(self):
        """Without exploration (random > 0.10), borderline candidates are filtered."""
        from unittest.mock import patch
        ctx = _ctx(score_threshold=6.0)
        cands = [_candidate(msg="explore this", relevance=5, timing=6, urgency=5, category="wellbeing")]
        with patch("donna.brain.rules.random.random", return_value=0.50):
            result = score_and_filter(cands, ctx)
        assert len(result) == 0

    def test_exploration_requires_minimum_score(self):
        """Exploration should not save candidates below DEFERRED_MIN_SCORE."""
        from unittest.mock import patch
        ctx = _ctx(score_threshold=6.0)
        # composite = 2*0.4 + 2*0.35 + 2*0.25 = 2.0 — way below threshold - 1.0
        cands = [_candidate(msg="too low", relevance=2, timing=2, urgency=2)]
        with patch("donna.brain.rules.random.random", return_value=0.05):
            result = score_and_filter(cands, ctx)
        assert len(result) == 0


class TestSuppression:
    def test_suppressed_category_filtered(self):
        """Candidates in suppressed categories are hard-filtered regardless of score."""
        ctx = _ctx()
        ctx["category_suppression"] = {
            "suppressed": {"wellbeing": {"reason": "low engagement"}}
        }
        cands = [
            _candidate(msg="wellbeing msg", relevance=9, timing=9, urgency=9, category="wellbeing"),
            _candidate(msg="deadline msg", relevance=9, timing=9, urgency=9, category="deadline_warning"),
        ]
        result = score_and_filter(cands, ctx)
        assert len(result) == 1
        assert result[0]["category"] == "deadline_warning"

    def test_non_suppressed_passes(self):
        """Candidates NOT in suppressed categories pass normally."""
        ctx = _ctx()
        ctx["category_suppression"] = {
            "suppressed": {"social": {"reason": "too many ignores"}}
        }
        cands = [_candidate(msg="deadline msg", relevance=8, timing=8, urgency=8, category="deadline_warning")]
        result = score_and_filter(cands, ctx)
        assert len(result) == 1

    def test_empty_suppression(self):
        """No suppressed categories means nothing filtered."""
        ctx = _ctx()
        ctx["category_suppression"] = {"suppressed": {}}
        cands = [_candidate(msg="msg", relevance=8, timing=8, urgency=8, category="wellbeing")]
        result = score_and_filter(cands, ctx)
        assert len(result) == 1


class TestExploration:
    def test_exploration_allows_borderline(self):
        """With random < 0.10, a borderline candidate passes."""
        # Score = 5*0.4 + 5*0.35 + 5*0.25 = 5.0, threshold default 5.5
        # 5.0 >= 5.5 - 1.0 = 4.5 and 5.0 >= DEFERRED_MIN_SCORE
        cands = [_candidate(msg="explore me", relevance=5, timing=5, urgency=5)]
        with patch("donna.brain.rules.random.random", return_value=0.05):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 1
        assert result[0].get("_explored") is True

    def test_exploration_does_not_fire_above_threshold(self):
        """Random < 0.10 but score >= threshold — normal pass, no _explored flag."""
        cands = [_candidate(msg="strong", relevance=7, timing=7, urgency=7)]
        with patch("donna.brain.rules.random.random", return_value=0.05):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 1
        assert "_explored" not in result[0]

    def test_exploration_blocked_when_random_high(self):
        """With random >= 0.10, borderline candidates are filtered normally."""
        cands = [_candidate(msg="no explore", relevance=5, timing=5, urgency=5)]
        with patch("donna.brain.rules.random.random", return_value=0.50):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 0

    def test_exploration_rejects_too_low(self):
        """Even with random < 0.10, candidates below threshold - 1.0 are rejected."""
        # Score = 3*0.4 + 3*0.35 + 3*0.25 = 3.0, threshold 5.5
        # 3.0 < 5.5 - 1.0 = 4.5 → rejected
        cands = [_candidate(msg="too low", relevance=3, timing=3, urgency=3)]
        with patch("donna.brain.rules.random.random", return_value=0.05):
            result = score_and_filter(cands, _ctx())
        assert len(result) == 0


class TestEmptyInput:
    def test_empty_candidates(self):
        assert score_and_filter([], _ctx()) == []

    def test_empty_context(self):
        cands = [_candidate(relevance=7, timing=7, urgency=7)]
        result = score_and_filter(cands, {})
        assert isinstance(result, list)
