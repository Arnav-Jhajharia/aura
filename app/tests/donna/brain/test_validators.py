"""Tests for donna/brain/validators.py."""

from donna.brain.validators import validate_format_constraints, validate_message, validate_template_params


def test_valid_message_passes():
    msg, warnings = validate_message("CS2103 due tomorrow 11:59pm. 3-5 is open.")
    assert msg == "CS2103 due tomorrow 11:59pm. 3-5 is open."
    assert warnings == []


def test_empty_message():
    msg, warnings = validate_message("")
    assert msg == ""
    assert "empty_message" in warnings


def test_long_message_truncated():
    long = "x" * 5000
    msg, warnings = validate_message(long)
    assert len(msg) <= 4096
    assert any("message_too_long" in w for w in warnings)


def test_banned_phrase_flagged():
    msg, warnings = validate_message("Just checking in to see how you're doing!")
    assert any("banned_phrase" in w for w in warnings)
    # Message is still returned (warning only, not blocked)
    assert msg


def test_signature_removed():
    msg, warnings = validate_message("CS2103 due tomorrow. — Donna")
    assert "Donna" not in msg
    assert msg == "CS2103 due tomorrow."


def test_bad_markdown_cleaned():
    msg, warnings = validate_message("## Schedule\n[Canvas](https://canvas.nus.edu)")
    assert "##" not in msg
    assert "](https" not in msg
    assert any("bad_markdown" in w for w in warnings)


def test_system_prompt_leakage_flagged():
    msg, warnings = validate_message("As an AI language model, I cannot do that.")
    assert any("possible_leakage" in w for w in warnings)


def test_validate_template_params_truncates():
    params = ["short", "x" * 2000]
    result = validate_template_params(params)
    assert len(result[0]) == 5
    assert len(result[1]) == 1024


class TestFormatConstraints:
    def test_text_valid(self):
        valid, reason = validate_format_constraints({"message": "hello"}, "text")
        assert valid is True
        assert reason is None

    def test_button_body_too_long(self):
        valid, reason = validate_format_constraints({"message": "x" * 1025}, "button")
        assert valid is False
        assert "button body too long" in reason

    def test_button_valid(self):
        valid, reason = validate_format_constraints({"message": "x" * 500}, "button")
        assert valid is True

    def test_list_too_many_rows(self):
        lines = "Header\n" + "\n".join(f"Row {i}" for i in range(12))
        valid, reason = validate_format_constraints({"message": lines}, "list")
        assert valid is False
        assert "too many rows" in reason

    def test_list_valid(self):
        lines = "Header\n" + "\n".join(f"Row {i}" for i in range(5))
        valid, reason = validate_format_constraints({"message": lines}, "list")
        assert valid is True

    def test_cta_invalid_url(self):
        candidate = {"message": "Check this", "data": {"link": "ftp://bad.com/file"}}
        valid, reason = validate_format_constraints(candidate, "cta_url")
        assert valid is False
        assert "invalid scheme" in reason

    def test_cta_valid(self):
        candidate = {"message": "Check this", "data": {"link": "https://example.com"}}
        valid, reason = validate_format_constraints(candidate, "cta_url")
        assert valid is True


class TestEmojiEnforcement:
    def test_single_emoji_passes(self):
        msg, warnings = validate_message("Day 14 of running \U0001F3C3")
        assert "\U0001F3C3" in msg
        assert not any("too_many_emojis" in w for w in warnings)

    def test_no_emoji_passes(self):
        msg, warnings = validate_message("CS2103 due tomorrow 11:59pm.")
        assert not any("too_many_emojis" in w for w in warnings)

    def test_multiple_emojis_stripped_to_one(self):
        msg, warnings = validate_message("Great job \U0001F389 keep going \U0001F4AA let's go \U0001F680")
        assert any("too_many_emojis" in w for w in warnings)
        # Count remaining emojis
        import re
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FA6F"
            "\U0001FA70-\U0001FAFF"
            "\U00002600-\U000026FF"
            "]+", re.UNICODE
        )
        remaining = emoji_pattern.findall(msg)
        assert len(remaining) == 1

    def test_three_separated_emojis_stripped(self):
        msg, warnings = validate_message("\U0001F600 hello \U0001F601 world \U0001F602")
        assert any("too_many_emojis" in w for w in warnings)
