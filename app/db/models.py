import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import DeclarativeBase, relationship


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    phone = Column(String, unique=True, nullable=False)
    name = Column(String)
    timezone = Column(String, default="UTC")
    wake_time = Column(String, default="08:00")
    sleep_time = Column(String, default="23:00")
    reminder_frequency = Column(String, default="normal")  # low, normal, high
    tone_preference = Column(String, default="casual")  # casual, balanced, formal
    onboarding_complete = Column(Boolean, default=False)
    onboarding_step = Column(String, nullable=True)  # awaiting_name | awaiting_timezone | awaiting_schedule | complete
    pending_action = Column(String, nullable=True)   # awaiting_canvas_token | awaiting_google_token
    created_at = Column(DateTime, default=datetime.utcnow)

    oauth_tokens = relationship("OAuthToken", back_populates="user")
    tasks = relationship("Task", back_populates="user")
    journal_entries = relationship("JournalEntry", back_populates="user")
    voice_notes = relationship("VoiceNote", back_populates="user")
    mood_logs = relationship("MoodLog", back_populates="user")
    expenses = relationship("Expense", back_populates="user")
    habits = relationship("Habit", back_populates="user")
    memory_facts = relationship("MemoryFact", back_populates="user")
    chat_messages = relationship("ChatMessage", back_populates="user")


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)  # canvas, google, microsoft
    access_token = Column(Text, nullable=False)  # encrypted at rest
    refresh_token = Column(Text)
    expires_at = Column(DateTime)
    scopes = Column(Text)

    user = relationship("User", back_populates="oauth_tokens")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    source = Column(String, default="manual")  # manual, canvas, email
    source_id = Column(String)
    due_date = Column(DateTime)
    priority = Column(Integer, default=2)  # 1=high, 2=medium, 3=low
    status = Column(String, default="pending")  # pending, done, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    user = relationship("User", back_populates="tasks")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    entry_type = Column(String, nullable=False)  # reflection, gratitude, brain_dump, vent
    content = Column(Text, nullable=False)
    mood_score = Column(Integer)  # 1-10
    embedding = Column(Vector(1536))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="journal_entries")


class VoiceNote(Base):
    __tablename__ = "voice_notes"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    audio_url = Column(String, nullable=False)
    duration_seconds = Column(Integer)
    transcript = Column(Text)
    summary = Column(Text)
    tags = Column(JSON)
    intent = Column(String)
    embedding = Column(Vector(1536))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="voice_notes")


class MoodLog(Base):
    __tablename__ = "mood_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    score = Column(Integer, nullable=False)  # 1-10
    note = Column(Text)
    source = Column(String, default="manual")  # manual, reflection, inferred
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="mood_logs")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    category = Column(String)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="expenses")


class Habit(Base):
    __tablename__ = "habits"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    target_frequency = Column(String, default="daily")
    current_streak = Column(Integer, default=0)
    longest_streak = Column(Integer, default=0)
    last_logged = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="habits")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    is_proactive = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="chat_messages")


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    fact = Column(Text, nullable=False)
    category = Column(String)  # preference, pattern, context, relationship
    confidence = Column(Float, default=0.8)
    embedding = Column(Vector(1536))
    source_message_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_referenced = Column(DateTime)

    user = relationship("User", back_populates="memory_facts")


class SignalState(Base):
    __tablename__ = "signal_states"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_signal_state_user_dedup"),
        Index("ix_signal_state_user_id", "user_id"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    dedup_key = Column(String, nullable=False)
    signal_type = Column(String, nullable=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    times_seen = Column(Integer, default=1)
    last_acted_on = Column(DateTime, nullable=True)
    suppressed_until = Column(DateTime, nullable=True)
