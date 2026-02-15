# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run locally
uvicorn api.main:app --reload

# Lint
ruff check . --target-version py311 --line-length 100

# Run with Docker
docker-compose up

# No test suite exists yet
```

Dependencies are managed via `pyproject.toml`. Install with `pip install -e ".[dev]"`.

## Architecture

Aura is a **WhatsApp-based personal assistant** for students. Users interact entirely via WhatsApp; the backend is a FastAPI app running a LangGraph agent pipeline.

### Request Flow

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
9. **memory_writer** (`nodes/memory.py`) — Extracts facts, persists memory, sends WhatsApp message

State is defined as a `TypedDict` in `agent/state.py`. LangGraph checkpoints state to Postgres via `langgraph-checkpoint-postgres`.

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

To add a new tool: implement in `tools/`, import in `executor.py`, add to `TOOL_REGISTRY`, and ensure the intent classifier LLM knows the tool name.

### LLM Usage

Nodes that call the LLM use `ChatOpenAI` with async `ainvoke()` and expect JSON-structured responses parsed from `response.content`. Config in `config.py` exposes `openai_api_key`.

### Database

- **ORM**: SQLAlchemy async (`asyncpg`) — session via `db/session.py`
- **Models** (`db/models.py`): `User`, `OAuthToken`, `Task`, `JournalEntry`, `VoiceNote`, `MoodLog`, `Expense`, `MemoryFact`
- **pgvector**: `JournalEntry`, `VoiceNote`, and `MemoryFact` have `Vector(1536)` embedding columns (semantic search not yet implemented)
- **Two connection URLs**: `DATABASE_URL` (asyncpg pooler for ORM), `DATABASE_URL_DIRECT` (psycopg direct for LangGraph checkpointer setup)
- Tables are created via `Base.metadata.create_all()` in the FastAPI lifespan; no Alembic migrations yet

### External Integrations (Composio)

Gmail, Google Calendar, and Canvas LMS integrations are managed via **Composio** (`tools/composio_client.py`). Composio handles OAuth token lifecycle (refresh, storage) and provides pre-built actions for each service.

- **Composio client**: Singleton in `tools/composio_client.py` — wraps sync SDK calls with `asyncio.to_thread()`
- **Tool execution**: `execute_tool(slug, user_id, arguments)` — all external API calls go through this
- **Auth flow**: Google uses Composio OAuth2 redirect (`api/auth.py`); Canvas uses paste-token flow registered via `connected_accounts.initiate(API_KEY)`
- **Connection check**: `get_connected_integrations(user_id)` queries Composio for active connections (used by `context_loader`)
- **OAuthToken model**: Kept in `db/models.py` for migration but no longer used by active code

### Configuration

All config loaded from `.env` via `pydantic-settings` in `config.py`. Required keys: `OPENAI_API_KEY`, `DATABASE_URL`, `DATABASE_URL_DIRECT`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `CANVAS_BASE_URL`, `COMPOSIO_API_KEY`, `COMPOSIO_GOOGLE_AUTH_CONFIG_ID`, `COMPOSIO_CANVAS_AUTH_CONFIG_ID`, `DEEPGRAM_API_KEY`, R2 storage credentials.

### Scheduler

`agent/scheduler.py` defines APScheduler jobs (morning briefing, water reminder, nightly reflection) but the scheduler is **not yet wired into the FastAPI lifespan**.

## Known Incomplete Areas

- pgvector semantic search in `tools/memory_search.py` and `tools/voice.py`
- Scheduler not started on app startup
- No test suite
- `OAuthToken` model kept for migration — remove after all users reconnect via Composio
