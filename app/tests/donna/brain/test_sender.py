"""Tests for donna/brain/sender.py — format selection, briefing, window status, truncation, retry."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from donna.brain.sender import (
    _build_briefing_sections,
    _get_window_status,
    _select_message_format,
    _truncate_at_word_boundary,
    send_with_retry,
)
from tools.whatsapp import WhatsAppResult
from tests.conftest import make_chat_message, make_user


def test_format_text_default():
    candidate = {"message": "CS2103 due tomorrow.", "action_type": "text", "category": "nudge"}
    assert _select_message_format(candidate) == "text"


def test_format_button_prompt():
    candidate = {"message": "Want me to block this?", "action_type": "button_prompt"}
    assert _select_message_format(candidate) == "button"


def test_format_list_for_briefing():
    message = "Tuesday.\nCS2103 10-12\nIS1108 3pm\nMA2001 due Friday\nNothing else."
    candidate = {"message": message, "action_type": "text", "category": "briefing"}
    assert _select_message_format(candidate) == "list"


def test_format_cta_for_grade_with_link():
    candidate = {
        "message": "MA2001 midterm: 78/100.",
        "action_type": "text",
        "category": "grade_alert",
        "data": {"link": "https://canvas.nus.edu/grades"},
    }
    assert _select_message_format(candidate) == "cta_url"


def test_format_text_for_grade_without_link():
    candidate = {
        "message": "MA2001 midterm: 78/100.",
        "action_type": "text",
        "category": "grade_alert",
    }
    assert _select_message_format(candidate) == "text"


def test_build_briefing_sections():
    message = "Tuesday.\nCS2103 10-12, COM1\nIS1108 3pm, AS6\nMA2001 due Friday"
    body, button_text, sections = _build_briefing_sections(message)
    assert body == "Tuesday."
    assert button_text == "View schedule"
    assert len(sections) == 1
    assert len(sections[0]["rows"]) == 3


def test_build_briefing_sections_empty():
    body, button_text, sections = _build_briefing_sections("")
    assert body == ""
    assert sections == []


class TestTruncateAtWordBoundary:
    def test_short_unchanged(self):
        assert _truncate_at_word_boundary("hello", 10) == "hello"

    def test_truncates_at_space(self):
        result = _truncate_at_word_boundary("hello world this is long", 13)
        assert result == "hello world"
        assert len(result) <= 13

    def test_no_space_hard_truncate(self):
        result = _truncate_at_word_boundary("abcdefghij", 5)
        assert result == "abcde"

    def test_exact_length(self):
        assert _truncate_at_word_boundary("hello", 5) == "hello"


class TestBuildBriefingSectionsImproved:
    def test_unique_ids(self):
        message = "Today.\nCS2103 10-12\nIS1108 3pm"
        _, _, sections = _build_briefing_sections(message)
        rows = sections[0]["rows"]
        ids = [r["id"] for r in rows]
        assert len(set(ids)) == len(ids)  # all unique

    def test_word_boundary_titles(self):
        message = "Today.\nCS2103 Software Engineering 10-12pm at COM1"
        _, _, sections = _build_briefing_sections(message)
        row = sections[0]["rows"][0]
        # Title should be at most 24 chars, truncated at word boundary
        assert len(row["title"]) <= 24
        # Should not cut in the middle of a word
        assert not row["title"].endswith("Engineeri")

    def test_meaningful_descriptions(self):
        message = "Today.\nCS2103 Software Engineering 10-12pm at COM1"
        _, _, sections = _build_briefing_sections(message)
        row = sections[0]["rows"][0]
        # Description should contain the remainder text
        assert len(row["description"]) <= 72


class TestGetWindowStatus:
    async def test_open(self, db_session, patch_async_session):
        """User message 1 hour ago → window open, safe for freeform."""
        user = make_user(id="ws-open")
        msg = make_chat_message(
            user_id="ws-open", role="user", content="hey",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add_all([user, msg])
        await db_session.commit()

        status = await _get_window_status("ws-open")
        assert status["open"] is True
        assert status["safe_for_freeform"] is True
        assert status["minutes_remaining"] > 60

    async def test_closed(self, db_session, patch_async_session):
        """No recent user messages → window closed."""
        user = make_user(id="ws-closed")
        db_session.add(user)
        await db_session.commit()

        status = await _get_window_status("ws-closed")
        assert status["open"] is False
        assert status["safe_for_freeform"] is False
        assert status["last_user_message_at"] is None

    async def test_closing_soon(self, db_session, patch_async_session):
        """User message 23h 57min ago → open but NOT safe for freeform."""
        user = make_user(id="ws-closing")
        msg = make_chat_message(
            user_id="ws-closing", role="user", content="hey",
            created_at=datetime.now(timezone.utc) - timedelta(hours=23, minutes=57),
        )
        db_session.add_all([user, msg])
        await db_session.commit()

        status = await _get_window_status("ws-closing")
        assert status["open"] is True
        assert status["safe_for_freeform"] is False
        assert status["minutes_remaining"] < 5

    async def test_no_messages(self, db_session, patch_async_session):
        """User exists but never sent a message → window closed."""
        user = make_user(id="ws-none")
        db_session.add(user)
        await db_session.commit()

        status = await _get_window_status("ws-none")
        assert status["open"] is False
        assert status["minutes_remaining"] == 0


class TestSendWithRetry:
    async def test_success_first_attempt(self):
        ok = WhatsAppResult(success=True, wa_message_id="wamid.ok")
        with patch("donna.brain.sender._send_freeform", new_callable=AsyncMock, return_value=ok):
            result = await send_with_retry("+123", {"message": "hi"}, "text")
        assert result.success is True

    async def test_format_fallback_to_text(self):
        """Unsupported format error → fallback to text succeeds."""
        fail = WhatsAppResult(success=False, fallback_format="text")
        ok = WhatsAppResult(success=True, wa_message_id="wamid.fb")

        call_count = 0

        async def mock_send(phone, candidate, fmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fail  # first attempt with original format
            return ok  # fallback to text

        with patch("donna.brain.sender._send_freeform", side_effect=mock_send):
            result = await send_with_retry("+123", {"message": "hi"}, "button")
        assert result.success is True
        assert call_count == 2

    async def test_invalid_format_falls_back_before_send(self):
        """Invalid format constraints → immediately falls back to text."""
        ok = WhatsAppResult(success=True, wa_message_id="wamid.val")
        candidate = {"message": "x" * 1025}  # too long for button body (1024 max)
        with patch("donna.brain.sender._send_freeform", new_callable=AsyncMock,
                    return_value=ok) as mock_send:
            result = await send_with_retry("+123", candidate, "button")
        assert result.success is True
        # Should have been called with "text", not "button"
        mock_send.assert_called_once_with("+123", candidate, "text")
