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

    # Academic profile
    academic_year = Column(Integer, nullable=True)
    faculty = Column(String, nullable=True)
    major = Column(String, nullable=True)
    graduation_year = Column(Integer, nullable=True)

    # Integration flags
    has_canvas = Column(Boolean, default=False)
    has_google = Column(Boolean, default=False)
    has_microsoft = Column(Boolean, default=False)
    nusmods_imported = Column(Boolean, default=False)

    # Multi-turn flow state (persisted between messages)
    pending_flow_json = Column(JSON, nullable=True)
    # Conversation summary (compressed history)
    conversation_summary = Column(Text, nullable=True)
    conversation_summary_message_count = Column(Integer, default=0)

    # Activity stats
    total_messages = Column(Integer, default=0)
    proactive_engagement_rate = Column(Float, nullable=True)
    avg_response_latency_seconds = Column(Float, nullable=True)
    last_active_at = Column(DateTime, nullable=True)

    oauth_tokens = relationship("OAuthToken", back_populates="user", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    journal_entries = relationship("JournalEntry", back_populates="user", cascade="all, delete-orphan")
    voice_notes = relationship("VoiceNote", back_populates="user", cascade="all, delete-orphan")
    mood_logs = relationship("MoodLog", back_populates="user", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="user", cascade="all, delete-orphan")
    habits = relationship("Habit", back_populates="user", cascade="all, delete-orphan")
    memory_facts = relationship("MemoryFact", back_populates="user", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")
    entities = relationship("UserEntity", back_populates="user", cascade="all, delete-orphan")
    behaviors = relationship("UserBehavior", back_populates="user", cascade="all, delete-orphan")


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String, nullable=False)  # canvas, google, microsoft
    access_token = Column(Text, nullable=False)  # encrypted at rest
    refresh_token = Column(Text)
    expires_at = Column(DateTime)
    scopes = Column(Text)

    user = relationship("User", back_populates="oauth_tokens")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entry_type = Column(String, nullable=False)  # reflection, gratitude, brain_dump, vent
    content = Column(Text, nullable=False)
    mood_score = Column(Integer)  # 1-10
    embedding = Column(Vector(1536))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="journal_entries")


class VoiceNote(Base):
    __tablename__ = "voice_notes"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    score = Column(Integer, nullable=False)  # 1-10
    note = Column(Text)
    source = Column(String, default="manual")  # manual, reflection, inferred
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="mood_logs")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    category = Column(String)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="expenses")


class Habit(Base):
    __tablename__ = "habits"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    is_proactive = Column(Boolean, default=False)
    wa_message_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="chat_messages")


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fact = Column(Text, nullable=False)
    category = Column(String)  # preference, pattern, context, relationship
    confidence = Column(Float, default=0.8)
    embedding = Column(Vector(1536))
    source_message_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_referenced = Column(DateTime)

    user = relationship("User", back_populates="memory_facts")


class UserEntity(Base):
    __tablename__ = "user_entities"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "name_normalized", name="uq_user_entity"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String, nullable=False)  # person, place, task, idea, event, preference
    name = Column(String, nullable=False)
    name_normalized = Column(String, nullable=False)  # lowercase stripped for dedup
    metadata_ = Column("metadata", JSON, default=dict)
    sentiment = Column(String, nullable=True)  # positive, negative, neutral
    mention_count = Column(Integer, default=1)
    first_mentioned = Column(DateTime, default=datetime.utcnow)
    last_mentioned = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="entities")


class UserBehavior(Base):
    __tablename__ = "user_behaviors"
    __table_args__ = (
        UniqueConstraint("user_id", "behavior_key", name="uq_user_behavior"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    behavior_key = Column(String, nullable=False)
    value = Column(JSON, nullable=False)
    confidence = Column(Float, default=0.5)
    sample_size = Column(Integer, default=0)
    last_computed = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="behaviors")


class SignalState(Base):
    __tablename__ = "signal_states"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_signal_state_user_dedup"),
        Index("ix_signal_state_user_id", "user_id"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dedup_key = Column(String, nullable=False)
    signal_type = Column(String, nullable=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    times_seen = Column(Integer, default=1)
    last_acted_on = Column(DateTime, nullable=True)
    suppressed_until = Column(DateTime, nullable=True)


class ProactiveFeedback(Base):
    __tablename__ = "proactive_feedback"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(String, nullable=False)
    category = Column(String)
    trigger_signals = Column(JSON)
    sent_at = Column(DateTime, default=datetime.utcnow)
    outcome = Column(String, default="pending")  # pending, engaged, ignored, negative, button_click
    response_latency_seconds = Column(Float, nullable=True)
    wa_message_id = Column(String, nullable=True)
    format_used = Column(String, nullable=True)          # text|button|list|cta_url|template
    template_name = Column(String, nullable=True)
    delivery_status = Column(String, default="sent")     # sent|delivered|read|failed
    delivery_failed_reason = Column(String, nullable=True)
    reply_sentiment = Column(String, nullable=True)      # positive|neutral|negative
    feedback_score = Column(Float, nullable=True)        # -1.0 to 1.0, from OUTCOME_HIERARCHY
    created_at = Column(DateTime, default=datetime.utcnow)


class DeferredInsight(Base):
    __tablename__ = "deferred_insights"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category = Column(String)
    message_draft = Column(Text)
    trigger_signals = Column(JSON)
    relevance_score = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)


class DeferredSend(Base):
    __tablename__ = "deferred_sends"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    candidate_json = Column(JSON, nullable=False)
    block_reason = Column(String)
    scheduled_for = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    attempted = Column(Boolean, default=False)
    expired = Column(Boolean, default=False)
