# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run locally
uvicorn api.main:app --reload

# Lint
ruff check . --target-version py311 --line-length 100

# Run tests
pytest tests/ -v --asyncio-mode=auto

# Run with Docker
docker-compose up
```

Dependencies are managed via `pyproject.toml`. Install with `pip install -e ".[dev]"`.

## Architecture

Aura is a **WhatsApp-based personal assistant** for students. Users interact entirely via WhatsApp; the backend is a FastAPI app running a LangGraph agent pipeline + a proactive messaging system (Donna).

### Request Flow (User-Initiated)

```
WhatsApp → POST /webhook → process_message() → LangGraph StateGraph → WhatsApp reply
```

The agent graph in `agent/graph.py` sequences these nodes:

1. **message_ingress** (`nodes/ingress.py`) — Lookup/create user by phone number
2. **route_after_ingress** — Branch: `token_collector` (pending OAuth) | `onboarding_handler` (new user) | `classify_type`
3. **classify_type** (`nodes/classifier.py`) — Route audio → `voice_transcriber`, else → `intent_classifier`
4. **voice_transcriber** (`nodes/transcriber.py`) — Download from WhatsApp, transcribe via Deepgram
5. **intent_classifier** (`nodes/classifier.py`) — LLM extracts `intent`, `entities`, `tools_needed`
6. **context_loader** (`nodes/context.py`) — Enrich `user_context` from DB (tasks, mood, deadlines)
7. **tool_executor** (`nodes/executor.py`) — Calls tools from `TOOL_REGISTRY` by name
8. **response_composer** (`nodes/composer.py`) — LLM generates WhatsApp-formatted reply
9. **memory_writer** (`nodes/memory.py`) — Extracts facts + entities, persists memory, sends WhatsApp message

### Proactive Messaging (Donna)

Donna runs on a 5-minute APScheduler interval and proactively messages users when context warrants it.

```
Scheduler → donna_loop(user_id) → signals → context → LLM candidates → score/filter → WhatsApp
```

**Signal Layer** (`donna/signals/`):
- `calendar.py` — polls Google Calendar for upcoming events, gaps, busy/empty days
- `canvas.py` — checks Canvas assignments for approaching/overdue deadlines
- `email.py` — checks Gmail for piling unread / important emails
- `internal.py` — time-based signals (morning/evening window, interaction gaps, mood trends, overdue tasks, habit streaks, memory relevance)
- `collector.py` — runs all 4 collectors concurrently, sorts by urgency

**Brain Layer** (`donna/brain/`):
- `context.py` — builds full context dict: user profile, signals, conversation history, memory facts, tasks, mood, spending, recalled memories, daily message count
- `candidates.py` — LLM (GPT-4o) generates 0-3 scored candidate messages
- `rules.py` — composite scoring (relevance×0.4 + timing×0.35 + urgency×0.25), hard filters: quiet hours (user timezone), cooldown (30min), daily cap (4), score threshold (5.5), dedup, urgent override (8.5)
- `sender.py` — sends via WhatsApp + persists as ChatMessage

**Memory Layer** (`donna/memory/`):
- `entities.py` — LLM extracts structured entities (person/place/task/event/idea/preference) from user messages, stores as MemoryFacts with `category="entity:<type>"`
- `recall.py` — LLM generates search queries from current context, keyword-searches MemoryFact via ILIKE
- `patterns.py` — LLM detects behavioral patterns from chat history + memory facts, stores as `category="pattern"`

**Main Loop** (`donna/loop.py`): signals → context → candidates → score → send. Returns number of messages sent.

**Scheduler** (`agent/scheduler.py`): `run_donna_for_all_users()` — queries onboarded users, runs `donna_loop` concurrently for each. Wired into FastAPI lifespan.

### Tool Registry Pattern

Tools are registered as plain async functions in `agent/nodes/executor.py`:

```python
TOOL_REGISTRY: dict[str, callable] = {
    "create_task": create_task,
    "get_canvas_assignments": get_canvas_assignments,
    # ...
}
```

All tool functions follow this signature:
```python
async def tool_name(user_id: str, entities: dict = None, **kwargs) -> list[dict] | dict:
```

### LLM Usage

Nodes that call the LLM use `ChatOpenAI` with async `ainvoke()` and expect JSON-structured responses parsed from `response.content`. Config in `config.py` exposes `openai_api_key`.

### Database

- **ORM**: SQLAlchemy async (`asyncpg`) — session via `db/session.py`
- **Models** (`db/models.py`): `User`, `OAuthToken`, `Task`, `JournalEntry`, `VoiceNote`, `MoodLog`, `Expense`, `Habit`, `MemoryFact`, `ChatMessage`
- **pgvector**: `JournalEntry`, `VoiceNote`, and `MemoryFact` have `Vector(1536)` embedding columns (semantic search not yet implemented)
- **Two connection URLs**: `DATABASE_URL` (asyncpg pooler for ORM), `DATABASE_URL_DIRECT` (psycopg direct for LangGraph checkpointer setup)
- Tables are created via `Base.metadata.create_all()` in the FastAPI lifespan; no Alembic migrations yet

### External Integrations

- **Google (Gmail + Calendar)**: Composio SDK (`tools/composio_client.py`). Composio handles OAuth token lifecycle. Chained OAuth flow: Gmail → Calendar.
- **Canvas LMS**: Direct httpx + OAuthToken (PAT paste flow). Composio doesn't support Canvas PAT paste.
- **Auth flow**: `api/auth.py` — Google via Composio OAuth2 redirect; Canvas via paste-token stored in OAuthToken table.

### Configuration

All config loaded from `.env` via `pydantic-settings` in `config.py`. Required keys: `OPENAI_API_KEY`, `DATABASE_URL`, `DATABASE_URL_DIRECT`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `CANVAS_BASE_URL`, `COMPOSIO_API_KEY`, `COMPOSIO_GMAIL_AUTH_CONFIG_ID`, `COMPOSIO_GCAL_AUTH_CONFIG_ID`, `DEEPGRAM_API_KEY`, R2 storage credentials.

### Testing

Tests live in `tests/` and use pytest + pytest-asyncio with an in-memory SQLite database (aiosqlite). The `conftest.py` patches `async_session` in all modules that import it to redirect DB operations to the test DB.

```bash
pytest tests/ -v --asyncio-mode=auto
```

## Known Incomplete Areas

- pgvector semantic search (currently using ILIKE keyword search)
- Pattern detection runs on-demand, not scheduled
- `OAuthToken` model kept for Canvas PAT storage
