"""Tests for donna/brain/template_filler.py."""

from donna.brain.template_filler import _naive_split, TEMPLATE_SLOT_COUNTS


def test_template_slot_counts():
    assert TEMPLATE_SLOT_COUNTS["donna_deadline_v2"] == 2
    assert TEMPLATE_SLOT_COUNTS["donna_check_in"] == 1
    assert TEMPLATE_SLOT_COUNTS["donna_class_reminder"] == 3


def test_naive_split_single_slot():
    result = _naive_split("CS2103 due tomorrow", 1)
    assert result == ["CS2103 due tomorrow"]


def test_naive_split_two_slots_dash():
    result = _naive_split("CS2103 Assignment 3 — tomorrow 11:59pm", 2)
    assert len(result) == 2
    assert result[0] == "CS2103 Assignment 3"
    assert result[1] == "tomorrow 11:59pm"


def test_naive_split_two_slots_period():
    result = _naive_split("CS2103 due tomorrow. You're free 3-5.", 2)
    assert len(result) == 2


def test_naive_split_padding():
    result = _naive_split("short", 3)
    assert len(result) == 3
    assert result[0] == "short"
    assert result[1] == ""
    assert result[2] == ""


def test_naive_split_truncates_long():
    long = "x" * 2000
    result = _naive_split(long, 1)
    assert len(result[0]) <= 1024
