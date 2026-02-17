"""Startup migrations — adds new columns to existing tables.

Idempotent on Postgres via ADD COLUMN IF NOT EXISTS.
Skipped on SQLite (tests use create_all which handles new columns).
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# (table, column, type, default)
_USER_COLUMNS = [
    ("users", "academic_year", "INTEGER", None),
    ("users", "faculty", "VARCHAR", None),
    ("users", "major", "VARCHAR", None),
    ("users", "graduation_year", "INTEGER", None),
    ("users", "has_canvas", "BOOLEAN", "FALSE"),
    ("users", "has_google", "BOOLEAN", "FALSE"),
    ("users", "has_microsoft", "BOOLEAN", "FALSE"),
    ("users", "nusmods_imported", "BOOLEAN", "FALSE"),
    ("users", "total_messages", "INTEGER", "0"),
    ("users", "proactive_engagement_rate", "DOUBLE PRECISION", None),
    ("users", "avg_response_latency_seconds", "DOUBLE PRECISION", None),
    ("users", "last_active_at", "TIMESTAMP", None),
    # Layer 5 — delivery tracking
    ("chat_messages", "wa_message_id", "VARCHAR", None),
    ("proactive_feedback", "wa_message_id", "VARCHAR", None),
    ("proactive_feedback", "format_used", "VARCHAR", None),
    ("proactive_feedback", "template_name", "VARCHAR", None),
    ("proactive_feedback", "delivery_status", "VARCHAR", "'sent'"),
    ("proactive_feedback", "delivery_failed_reason", "VARCHAR", None),
    # Layer 6 — feedback processing
    ("proactive_feedback", "reply_sentiment", "VARCHAR", None),
    ("proactive_feedback", "feedback_score", "DOUBLE PRECISION", None),
]

# (table, fk_column, constraint_name) — all reference users(id)
_CASCADE_FKS = [
    ("oauth_tokens", "user_id", "oauth_tokens_user_id_fkey"),
    ("tasks", "user_id", "tasks_user_id_fkey"),
    ("journal_entries", "user_id", "journal_entries_user_id_fkey"),
    ("voice_notes", "user_id", "voice_notes_user_id_fkey"),
    ("mood_logs", "user_id", "mood_logs_user_id_fkey"),
    ("expenses", "user_id", "expenses_user_id_fkey"),
    ("habits", "user_id", "habits_user_id_fkey"),
    ("chat_messages", "user_id", "chat_messages_user_id_fkey"),
    ("memory_facts", "user_id", "memory_facts_user_id_fkey"),
    ("user_entities", "user_id", "user_entities_user_id_fkey"),
    ("user_behaviors", "user_id", "user_behaviors_user_id_fkey"),
    ("signal_states", "user_id", "signal_states_user_id_fkey"),
    ("proactive_feedback", "user_id", "proactive_feedback_user_id_fkey"),
    ("deferred_insights", "user_id", "deferred_insights_user_id_fkey"),
    ("deferred_sends", "user_id", "deferred_sends_user_id_fkey"),
]

_NEW_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS deferred_sends (
        id VARCHAR PRIMARY KEY,
        user_id VARCHAR NOT NULL REFERENCES users(id),
        candidate_json JSONB NOT NULL,
        block_reason VARCHAR,
        scheduled_for TIMESTAMP NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        attempted BOOLEAN DEFAULT FALSE,
        expired BOOLEAN DEFAULT FALSE
    )
    """,
]


async def run_startup_migrations(engine: AsyncEngine) -> None:
    """Run idempotent ALTER TABLE ADD COLUMN IF NOT EXISTS for new columns.

    Only runs on Postgres (SQLite tests use create_all which builds fresh tables).
    """
    if "sqlite" in str(engine.url):
        logger.debug("Skipping startup migrations on SQLite")
        return

    async with engine.begin() as conn:
        for table, column, col_type, default in _USER_COLUMNS:
            default_clause = f" DEFAULT {default}" if default is not None else ""
            sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}{default_clause}"
            try:
                await conn.execute(text(sql))
            except Exception:
                logger.debug("Migration skipped for %s.%s (may already exist)", table, column)

        for ddl in _NEW_TABLES_SQL:
            try:
                await conn.execute(text(ddl))
            except Exception:
                logger.debug("Table creation skipped (may already exist)")

        # ── Add ON DELETE CASCADE to all user_id foreign keys ──────────
        for table, fk_col, constraint_name in _CASCADE_FKS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint_name}"
                ))
                await conn.execute(text(
                    f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} "
                    f"FOREIGN KEY ({fk_col}) REFERENCES users(id) ON DELETE CASCADE"
                ))
            except Exception:
                logger.debug("CASCADE migration skipped for %s.%s", table, fk_col)

    logger.info("Startup migrations complete")
