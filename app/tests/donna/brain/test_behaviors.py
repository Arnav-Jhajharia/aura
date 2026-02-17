"""Tests for donna/brain/behaviors.py."""

from datetime import datetime, timezone

import pytest

from donna.brain.behaviors import (
    compute_active_hours,
    compute_language_register,
    compute_message_length_pref,
)
from tests.conftest import make_chat_message, make_user


@pytest.mark.asyncio
async def test_compute_active_hours(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)

    now = datetime.now(timezone.utc)
    # Add messages at hours 9, 9, 10, 14
    for hour in [9, 9, 10, 14]:
        ts = now.replace(hour=hour, minute=0)
        db_session.add(make_chat_message(user.id, role="user", content="hi", created_at=ts))
    await db_session.commit()

    result = await compute_active_hours(user.id)
    assert result["sample_size"] == 4
    assert 9 in result["value"]["peak_hours"]


@pytest.mark.asyncio
async def test_compute_message_length_pref_short(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)

    now = datetime.now(timezone.utc)
    for msg in ["hi", "ok", "yes", "no", "lol"]:
        db_session.add(make_chat_message(user.id, role="user", content=msg, created_at=now))
    await db_session.commit()

    result = await compute_message_length_pref(user.id)
    assert result["sample_size"] == 5
    assert result["value"]["preference"] == "short"


@pytest.mark.asyncio
async def test_compute_message_length_pref_long(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)

    now = datetime.now(timezone.utc)
    long_msg = " ".join(["word"] * 25)
    for _ in range(5):
        db_session.add(make_chat_message(user.id, role="user", content=long_msg, created_at=now))
    await db_session.commit()

    result = await compute_message_length_pref(user.id)
    assert result["value"]["preference"] == "long"


@pytest.mark.asyncio
async def test_compute_active_hours_empty(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)
    await db_session.commit()

    result = await compute_active_hours(user.id)
    assert result["sample_size"] == 0
    assert result["value"]["peak_hours"] == []


@pytest.mark.asyncio
async def test_compute_language_register_formal(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)

    now = datetime.now(timezone.utc)
    formal_msgs = [
        "Thank you for the reminder. I will complete the assignment today.",
        "Could you please check my schedule for tomorrow?",
        "That would be very helpful. I appreciate the information.",
        "I have noted the deadline. Will start working on it soon.",
        "Please send me the details for the meeting.",
    ]
    for msg in formal_msgs:
        db_session.add(make_chat_message(user.id, role="user", content=msg, created_at=now))
    await db_session.commit()

    result = await compute_language_register(user.id)
    assert result["sample_size"] == 5
    assert result["value"]["level"] == "formal"


@pytest.mark.asyncio
async def test_compute_language_register_very_casual(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)

    now = datetime.now(timezone.utc)
    casual_msgs = ["ya ok lol", "k bruh", "haha nah", "idk tbh", "nope lmao"]
    for msg in casual_msgs:
        db_session.add(make_chat_message(user.id, role="user", content=msg, created_at=now))
    await db_session.commit()

    result = await compute_language_register(user.id)
    assert result["sample_size"] == 5
    assert result["value"]["level"] == "very_casual"


@pytest.mark.asyncio
async def test_compute_language_register_empty(db_session, patch_async_session):
    user = make_user()
    db_session.add(user)
    await db_session.commit()

    result = await compute_language_register(user.id)
    assert result["sample_size"] == 0
    assert result["value"]["level"] == "casual"
