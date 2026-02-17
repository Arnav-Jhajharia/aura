"""Tests for donna/voice.py — tone engine."""

from donna.voice import DONNA_CORE_VOICE, DONNA_WHATSAPP_FORMAT, build_tone_section


def test_voice_constants_not_empty():
    assert "direct" in DONNA_CORE_VOICE.lower() or "warm" in DONNA_CORE_VOICE.lower()
    assert "whatsapp" in DONNA_WHATSAPP_FORMAT.lower()


def test_tone_section_empty_context():
    result = build_tone_section({})
    assert result == ""


def test_tone_section_low_mood():
    ctx = {"recent_moods": [{"score": 2}]}
    result = build_tone_section(ctx)
    assert "low" in result.lower()
    assert "pressure" in result.lower()


def test_tone_section_high_mood():
    ctx = {"recent_moods": [{"score": 9}]}
    result = build_tone_section(ctx)
    assert "energetic" in result.lower() or "punchy" in result.lower()


def test_tone_section_recent_conversation():
    ctx = {"minutes_since_last_message": 10}
    result = build_tone_section(ctx)
    assert "brief" in result.lower()


def test_tone_section_long_silence():
    ctx = {"minutes_since_last_message": 500}
    result = build_tone_section(ctx)
    assert "standalone" in result.lower()


def test_tone_section_short_message_pref():
    ctx = {"user_behaviors": {"message_length_pref": {"preference": "short"}}}
    result = build_tone_section(ctx)
    assert "short" in result.lower() or "2 sentences" in result.lower()


def test_tone_section_formal_register():
    ctx = {"user_behaviors": {"language_register": {"level": "formal"}}}
    result = build_tone_section(ctx)
    assert "formal" in result.lower()


def test_tone_section_very_casual_register():
    ctx = {"user_behaviors": {"language_register": {"level": "very_casual"}}}
    result = build_tone_section(ctx)
    assert "casual" in result.lower()


def test_tone_section_user_tone_preference():
    ctx = {"user": {"tone_preference": "formal"}}
    result = build_tone_section(ctx)
    assert "formal" in result.lower()


def test_tone_section_combined():
    ctx = {
        "recent_moods": [{"score": 3}],
        "minutes_since_last_message": 5,
        "user_behaviors": {"message_length_pref": {"preference": "short"}},
    }
    result = build_tone_section(ctx)
    assert "TONE CALIBRATION" in result
    # All three signals should be present
    assert "TONE:" in result
    assert "RECENCY:" in result
    assert "LENGTH:" in result
