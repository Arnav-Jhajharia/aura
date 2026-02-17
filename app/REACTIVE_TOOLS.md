# Aura Reactive System — Tool Registry & Architecture

## Overview

Aura's reactive system handles user-initiated WhatsApp messages through a LangGraph StateGraph with a ReAct planner loop. The planner decides which tools to call, executes them one at a time, observes results, and either calls another tool or hands off to the response composer. Maximum 3 tool calls per turn.

```
WhatsApp → POST /webhook → process_message()
  → message_ingress
  → [onboarding | token_collector | classify_type]
  → intent_classifier
  → thin_context_loader
  → planner ⟲ tool_executor (up to 3 iterations)
  → response_composer
  → memory_writer
  → WhatsApp reply
```

---

## Tool Routing

### Deterministic Keyword Routing (Iteration 0)

Before the LLM planner runs, `_deterministic_route()` checks the user's message against keyword patterns. If matched and the required integration is connected, the tool fires immediately — no LLM call needed.

| Keywords | Tool | Requires |
|----------|------|----------|
| "my courses", "am i taking", "enrolled in" | `canvas_courses` | canvas |
| "assignment", "what's due", "deadline" | `canvas_assignments` | canvas |
| "grade", "marks", "gpa", "results" | `canvas_grades` | canvas |
| "announcement", "prof said", "course news" | `canvas_announcements` | canvas |
| "did i submit", "missing submission" | `canvas_submission_status` | canvas |
| "calendar", "schedule", "what's on" | `get_calendar_events` | google/microsoft |
| "when am i free", "free slot", "find time" | `find_free_slots` | google/microsoft |
| "email", "inbox", "unread" | `get_emails` | google/microsoft |
| "nusmods.com/timetable", "sync timetable" | `sync_nusmods_to_calendar` | google/microsoft |
| "my tasks", "todo", "pending tasks" | `get_tasks` | — |
| "mood history", "how have i been" | `get_mood_history` | — |
| "spending", "expenses", "expense summary" | `get_expense_summary` | — |
| "voice note", "what did i say" | `search_voice_notes` | — |

### LLM Planner (Iterations 1+)

If no keyword match fires, or after the first tool result, the LLM planner (GPT-4o) receives the accumulated tool results, user message, intent, entities, conversation history, user profile, and connected integrations. It returns JSON deciding the next action.

### Fast-Path Intents (Zero Tools)

These intents skip the planner entirely: `thought`, `vent`, `info_dump`, `reflection`, `capabilities`.

---

## Tool Registry — 27 Tools

All tools follow this signature:

```python
async def tool_name(user_id: str, entities: dict = None, **kwargs) -> list[dict] | dict
```

Registered in `agent/nodes/executor.py` as a flat `TOOL_REGISTRY` dict mapping string names to callables.

---

### Canvas LMS (6 tools)

Requires: `canvas` integration (PAT stored in OAuthToken table)
API: Direct httpx calls to Canvas REST API with pagination support

| Tool | Description | Key Args |
|------|-------------|----------|
| `canvas_courses` | Enrolled courses (id, name, code, term) | — |
| `canvas_assignments` | Upcoming assignments with due dates | `days_ahead` (default 7) |
| `canvas_grades` | Recent graded submissions across all courses | — |
| `canvas_announcements` | Latest announcements across all courses (up to 15) | — |
| `canvas_course_info` | Detailed course info (syllabus, instructors) | `course_name` or `course_id` |
| `canvas_submission_status` | Submission status for upcoming assignments (next 14 days) | — |

**File:** `tools/canvas.py`

**Implementation notes:**
- `_fetch_all_pages()` handles Canvas Link-header pagination
- `_get_canvas_token()` retrieves PAT from the `OAuthToken` table
- Announcements fetched via `/discussion_topics?only_announcements=true` per course (capped at 10 courses, 3 per course)
- Course info search: if no `course_id`, fuzzy-matches `course_name` against enrolled courses
- HTML stripped from announcements and syllabi with regex

---

### Calendar (5 tools)

Requires: `google` or `microsoft` integration via Composio
Provider detection: `get_email_provider()` returns `"google"` or `"microsoft"`

| Tool | Description | Key Args |
|------|-------------|----------|
| `get_calendar_events` | Fetch events for a date range | `date`, `days` (default 1) |
| `create_calendar_event` | Create a new event | `title`, `start`, `end`, `description` |
| `find_free_slots` | Find free time slots in a day | `date`, `min_duration_minutes` (default 60) |
| `update_calendar_event` | Update an existing event | `event_id` + any of: `title`, `start`, `end`, `description`, `location` |
| `delete_calendar_event` | Delete an event by ID | `event_id` |

**File:** `tools/calendar.py`

**Composio action slugs:**

| Action | Google | Microsoft |
|--------|--------|-----------|
| List events | `GOOGLECALENDAR_FIND_EVENT` | `OUTLOOK_GET_CALENDAR_VIEW` |
| Create event | `GOOGLECALENDAR_CREATE_EVENT` | `OUTLOOK_CALENDAR_CREATE_EVENT` |
| Free slots | `GOOGLECALENDAR_FIND_FREE_SLOTS` | `OUTLOOK_FIND_MEETING_TIMES` |
| Update event | `GOOGLECALENDAR_UPDATE_EVENT` | `OUTLOOK_CALENDAR_UPDATE_EVENT` |
| Delete event | `GOOGLECALENDAR_DELETE_EVENT` | `OUTLOOK_CALENDAR_DELETE_EVENT` |

**Implementation notes:**
- `_normalize_events()` converts both providers to common `{title, start, end, location}` format
- `find_free_slots` has a local gap-finding fallback if the provider API fails (scans 8am–10pm)
- All datetimes use RFC3339 UTC format

---

### Email (4 tools)

Requires: `google` or `microsoft` integration via Composio

| Tool | Description | Key Args |
|------|-------------|----------|
| `get_emails` | List recent emails (subjects, snippets) | `filter` (unread/important/all), `count` (default 10) |
| `get_email_detail` | Full email body by ID | `email_id` |
| `reply_to_email` | Reply to a specific email | `email_id`, `body` |
| `send_email` | Send a new email | `to`, `subject`, `body` |

**File:** `tools/email.py`

**Composio action slugs:**

| Action | Google | Microsoft |
|--------|--------|-----------|
| List emails | `GMAIL_FETCH_EMAILS` | `OUTLOOK_FETCH_EMAILS` |
| Get email | `GMAIL_GET_EMAIL` | `OUTLOOK_FETCH_EMAILS` (filtered) |
| Reply | `GMAIL_REPLY_TO_THREAD` | `OUTLOOK_REPLY_EMAIL` |
| Send | `GMAIL_SEND_EMAIL` | `OUTLOOK_SEND_EMAIL` |

**Implementation notes:**
- Gmail uses query syntax (`is:unread`, `is:important`); Outlook uses OData filters (`isRead eq false`)
- Email list returns normalized `{id, from, subject, date, snippet}` dicts

---

### Tasks & Productivity (4 tools)

| Tool | Description | Key Args | Requires |
|------|-------------|----------|----------|
| `create_task` | Create a task/reminder | `title`, `due_date` | — |
| `get_tasks` | List pending tasks | — | — |
| `complete_task` | Mark a task complete | `task_id` | — |
| `sync_nusmods_to_calendar` | Parse NUSMods URL, create calendar events | `nusmods_url` | google/microsoft |

**Files:** `tools/tasks.py`, `tools/nusmods.py`

**NUSMods sync implementation (`tools/nusmods.py`):**
- Parses NUSMods share URLs: `https://nusmods.com/timetable/sem-2/share?CS2103T=LEC:G17&...`
- Fetches module data from `https://api.nusmods.com/v2/{AY}/modules/{code}.json`
- Computes actual dates from NUS week numbers (accounts for recess week between weeks 6–7)
- Creates recurring Google/Outlook calendar events with RRULE + EXDATE for recess
- Falls back to individual events if recurrence fails
- Creates exam events from `semesterData.examDate`
- Returns: `{modules_synced, events_created, exams_created, semester, academic_year, errors}`

---

### Journal & Mood (5 tools)

| Tool | Description | Key Args |
|------|-------------|----------|
| `save_journal_entry` | Save a journal entry | `content`, `entry_type` |
| `log_mood` | Log a mood score | `score` (1–10), `note` |
| `get_mood_history` | Recent mood scores | `days` (default 7) |
| `log_expense` | Log an expense | `amount`, `category`, `description` |
| `get_expense_summary` | Spending summary | `days` (default 7) |

**Files:** `tools/journal.py`, `tools/expenses.py`

---

### Memory & Context (4 tools)

| Tool | Description | Key Args |
|------|-------------|----------|
| `search_memory` | Search stored MemoryFacts by keyword | `query` |
| `search_voice_notes` | Search voice note transcripts | `query` |
| `get_voice_note_summary` | Full transcript of a specific voice note | `voice_note_id` |
| `recall_context` | Load structured DB data | `aspect` (tasks/moods/deadlines/expenses/deferred_insights) |

**Files:** `tools/memory_search.py`, `tools/voice.py`, `tools/recall_context.py`

**Implementation notes:**
- `search_memory` and `search_voice_notes` use ILIKE keyword search (pgvector semantic search not yet implemented)
- `recall_context` loads specific slices of DB data on demand instead of loading everything upfront

---

## External Integration Architecture

### Composio SDK (`tools/composio_client.py`)

Singleton `Composio` client wraps all Google and Microsoft API calls. All Composio SDK calls are synchronous, wrapped with `asyncio.to_thread()`.

| Function | Purpose |
|----------|---------|
| `execute_tool(slug, user_id, arguments)` | Execute a Composio action |
| `get_connected_integrations(user_id)` | List active providers (google, microsoft, canvas) |
| `get_email_provider(user_id)` | Returns "google", "microsoft", or "" |
| `initiate_connection(user_id, auth_config_id)` | Start OAuth flow |

### Canvas LMS (Direct HTTP)

Canvas uses a Personal Access Token (PAT) stored in the `OAuthToken` table. Direct httpx calls with `Authorization: Bearer {token}` header. Base URL from `settings.canvas_base_url`.

### Auth Flows

| Provider | Method | Details |
|----------|--------|---------|
| Google (Gmail + Calendar) | Composio OAuth2 | Chained: Gmail → Calendar |
| Microsoft (Outlook + Calendar) | Composio OAuth2 | Single flow covers both |
| Canvas | PAT paste | User pastes token, stored in OAuthToken |

---

## Planner Prompt Rules (Key Behaviors)

1. Only call tools if the required integration is connected
2. Deterministic routing fires first for obvious requests (iteration 0 only)
3. `search_memory` for anything referencing the past not in immediate context
4. `recall_context` for structured data (tasks, moods, expenses, deadlines)
5. Canvas tools: `canvas_assignments` for deadlines, `canvas_courses` for enrollment, `canvas_submission_status` for "did I submit?", `canvas_announcements` for course news, `canvas_course_info` for syllabus/instructor
6. Email: `get_email_detail` before replying (need the full body), `reply_to_email` with email_id + body
7. NUSMods URL detected → `sync_nusmods_to_calendar`
8. Thoughts, vents, reflections → zero tools, straight to composer

---

## Database Models (Relevant)

| Model | Purpose |
|-------|---------|
| `User` | Profile (name, timezone, onboarding state) |
| `OAuthToken` | Canvas PAT storage |
| `Task` | User tasks/reminders |
| `JournalEntry` | Journal entries (has Vector(1536) column) |
| `VoiceNote` | Voice note transcripts (has Vector(1536) column) |
| `MoodLog` | Mood scores |
| `Expense` | Expense logs |
| `MemoryFact` | Extracted facts, entities, patterns (has Vector(1536) column) |
| `ChatMessage` | Conversation history |

ORM: SQLAlchemy async with asyncpg. No Alembic migrations — tables created via `Base.metadata.create_all()`.

---

## File Map

```
tools/
├── canvas.py          # 6 tools — courses, assignments, grades, announcements, course info, submissions
├── calendar.py        # 5 tools — events, create, free slots, update, delete
├── email.py           # 4 tools — list, detail, reply, send
├── tasks.py           # 3 tools — create, get, complete
├── journal.py         # 3 tools — journal entry, mood log, mood history
├── expenses.py        # 2 tools — log expense, summary
├── voice.py           # 2 tools — search voice notes, get summary
├── nusmods.py         # 1 tool  — NUSMods timetable → calendar sync
├── memory_search.py   # 1 tool  — search MemoryFacts
├── recall_context.py  # 1 tool  — load specific DB context slices
└── composio_client.py # Composio SDK wrapper (execute, connections, auth)

agent/
├── graph.py           # LangGraph StateGraph definition, routing, process_message()
├── state.py           # AuraState TypedDict
├── discovery.py       # Progressive discovery hints (tool-triggered only)
├── scheduler.py       # APScheduler wiring for Donna proactive loop
└── nodes/
    ├── ingress.py     # Lookup/create user, load conversation history
    ├── onboarding.py  # Donna-personality onboarding flow
    ├── classifier.py  # Audio/text routing + intent classification
    ├── transcriber.py # Deepgram voice transcription
    ├── context.py     # Thin context loader (~300 tokens)
    ├── planner.py     # ReAct planner + deterministic routing
    ├── executor.py    # Tool registry (27 tools) + execution
    ├── composer.py    # LLM response generation
    ├── memory.py      # Fact extraction + persistence
    ├── naturalizer.py # Response cleanup
    └── token_collector.py # OAuth/PAT token handling
```
