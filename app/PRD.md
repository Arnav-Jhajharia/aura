# AURA — WhatsApp Life OS

> **Your personal life operating system that lives in WhatsApp.**
> Stay ahead of yourself.

---

## 1. What Is This

Aura is a WhatsApp chatbot that acts as your personal assistant, accountability partner, and life logger. It connects to your school (Canvas LMS), email (Gmail/Outlook), calendar, and health habits — all through the app you already check 50+ times a day.

You can text it, send voice notes, ask it questions, log expenses, journal your day, and it proactively reminds you to drink water, eat lunch, study for exams, and reflect on your day.

**Core thesis:** The best productivity system is the one you already use. WhatsApp is that system.

---

## 2. Architecture

```
WhatsApp (Meta Cloud API / Twilio)
        │
        ▼
   FastAPI Webhook Server
        │
        ▼
   LangGraph Agent (stateful graph)
   ┌────┴─────────────────────────┐
   │  Nodes:                      │
   │  ├─ message_ingress          │
   │  ├─ classify_type            │
   │  ├─ voice_transcriber        │
   │  ├─ intent_classifier        │
   │  ├─ context_loader           │
   │  ├─ tool_executor            │
   │  ├─ response_composer        │
   │  └─ memory_writer            │
   └────┬─────────────────────────┘
        │
   Tool Layer (LangChain Tools)
   ┌────┴─────────────────────────┐
   │  ├─ Canvas API               │
   │  ├─ Gmail / Outlook          │
   │  ├─ Google Calendar          │
   │  ├─ Whisper / Deepgram       │
   │  ├─ Task Manager (DB)        │
   │  ├─ Journal / Mood (DB)      │
   │  ├─ Expense Tracker (DB)     │
   │  └─ Memory Search (pgvector) │
   └──────────────────────────────┘
        │
   Persistence
   ┌────┴─────────────────────────┐
   │  ├─ PostgreSQL + pgvector    │
   │  ├─ Redis (LangGraph state)  │
   │  └─ Cloudflare R2 / S3      │
   └──────────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|---|---|
| Messaging | Meta Cloud API or Twilio |
| Server | FastAPI (Python) |
| Agent Framework | LangGraph |
| LLM | Claude API (via langchain-anthropic) |
| Transcription | Whisper API or Deepgram |
| Database | PostgreSQL + pgvector |
| Cache / State | Redis (LangGraph checkpointer) |
| File Storage | Cloudflare R2 or S3 |
| Scheduler | APScheduler |
| Hosting | Railway / Fly.io |

---

## 3. Project Structure

```
aura/
├── api/
│   ├── main.py              # FastAPI app, lifespan, CORS
│   ├── webhook.py           # WhatsApp webhook verification + message ingress
│   └── auth.py              # OAuth flow handlers (Canvas, Google, Microsoft)
├── agent/
│   ├── graph.py             # Main LangGraph StateGraph definition
│   ├── state.py             # AuraState TypedDict
│   ├── nodes/
│   │   ├── ingress.py       # message_ingress node
│   │   ├── classifier.py    # classify_type + intent_classifier nodes
│   │   ├── transcriber.py   # voice_transcriber node
│   │   ├── context.py       # context_loader node
│   │   ├── executor.py      # tool_executor node
│   │   ├── composer.py      # response_composer node
│   │   └── memory.py        # memory_writer node
│   └── scheduler.py         # APScheduler jobs for proactive nudges
├── tools/
│   ├── canvas.py            # Canvas LMS API (assignments, grades)
│   ├── email.py             # Gmail + Outlook (read, send, triage)
│   ├── calendar.py          # Google Calendar + Outlook Calendar
│   ├── voice.py             # Voice note download + transcription
│   ├── tasks.py             # Task CRUD operations
│   ├── journal.py           # Journal entries + mood logging
│   ├── expenses.py          # Expense tracking
│   ├── memory_search.py     # Semantic search over user memory (pgvector)
│   └── whatsapp.py          # WhatsApp message sending utilities
├── db/
│   ├── models.py            # SQLAlchemy models
│   ├── session.py           # Database session management
│   └── migrations/          # Alembic migrations
├── config.py                # Pydantic settings (env var loading)
├── docker-compose.yml       # PostgreSQL, Redis, app
├── Dockerfile
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 4. State Schema

This is the state that flows through every node in the LangGraph agent:

```python
from typing import TypedDict, Optional, Literal, Annotated
from langgraph.graph.message import add_messages

class AuraState(TypedDict):
    user_id: str
    message_type: Literal["text", "voice", "image", "location"]
    raw_input: str
    transcription: Optional[str]
    intent: Optional[str]  # task | question | thought | vent | command | reflection
    entities: dict  # extracted names, dates, amounts, topics
    tool_results: list[dict]
    user_context: dict  # loaded from DB: schedule, mood, tasks, deadlines
    response: Optional[str]
    messages: Annotated[list, add_messages]
    memory_updates: list[dict]  # new facts to persist about the user
```

---

## 5. LangGraph Graph

### Main Graph (user-triggered)

```
START → message_ingress → classify_type
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
         [text/image]                    [voice]
              │                               │
              ▼                               ▼
         intent_classifier ◄──── voice_transcriber
              │
              ▼
         context_loader
              │
              ▼
         tool_executor
              │
              ▼
         response_composer
              │
              ▼
         memory_writer → END (send WhatsApp message)
```

### Graph Construction

```python
from langgraph.graph import StateGraph, END

graph = StateGraph(AuraState)

# Add nodes
graph.add_node("message_ingress", message_ingress)
graph.add_node("classify_type", classify_type)
graph.add_node("voice_transcriber", voice_transcriber)
graph.add_node("intent_classifier", intent_classifier)
graph.add_node("context_loader", context_loader)
graph.add_node("tool_executor", tool_executor)
graph.add_node("response_composer", response_composer)
graph.add_node("memory_writer", memory_writer)

# Edges
graph.set_entry_point("message_ingress")
graph.add_edge("message_ingress", "classify_type")

# Conditional: voice goes to transcriber, everything else to intent classifier
graph.add_conditional_edges("classify_type", route_by_type, {
    "voice": "voice_transcriber",
    "text": "intent_classifier",
    "image": "intent_classifier",
})
graph.add_edge("voice_transcriber", "intent_classifier")
graph.add_edge("intent_classifier", "context_loader")
graph.add_edge("context_loader", "tool_executor")
graph.add_edge("tool_executor", "response_composer")
graph.add_edge("response_composer", "memory_writer")
graph.add_edge("memory_writer", END)

# Compile with Redis checkpointer
from langgraph.checkpoint.redis import RedisSaver
checkpointer = RedisSaver(redis_url=REDIS_URL)
app = graph.compile(checkpointer=checkpointer)
```

### Scheduler Subgraph (cron-triggered, not user-triggered)

Runs independently via APScheduler. For each user, it:
1. Checks current time vs user timezone and preferences
2. Loads user context (calendar, tasks, deadlines, mood history)
3. Determines which nudges are appropriate right now
4. Generates and sends messages via WhatsApp API

Scheduled jobs:
- **Morning briefing** (user's wake time): schedule, deadlines, unread emails
- **Water reminders** (every 2h during waking hours, skip during calendar events)
- **Meal reminders** (adaptive timing based on user patterns)
- **Deadline warnings** (72h, 24h, 3h before due)
- **Nightly reflection** (user's bedtime): "What made today worth it?"
- **Weekly recap** (Sunday evening): stats, mood trends, highlights

---

## 6. Node Specifications

### message_ingress
- Parses the incoming WhatsApp webhook payload
- Extracts: sender phone number, message type, message content/media URL
- Looks up or creates user in DB
- Loads user preferences (timezone, reminder settings, tone preference)
- Populates `user_id`, `message_type`, `raw_input` in state

### classify_type
- Determines `message_type`: text, voice, image, location
- Routes to appropriate next node via conditional edge

### voice_transcriber
- Downloads voice note audio from WhatsApp media URL
- Uploads to Cloudflare R2/S3 for storage
- Sends to Whisper API or Deepgram for transcription
- Stores voice note record in DB (audio_url, transcript, timestamp)
- Sets `transcription` in state (subsequent nodes use this instead of `raw_input`)

### intent_classifier
- Uses Claude to classify user intent from the message (or transcription)
- Intent categories: `task`, `question`, `thought`, `vent`, `command`, `reflection`
- Extracts entities: dates, people, amounts, project names, topics
- Sets `intent` and `entities` in state

**System prompt for classification:**
```
You are classifying a WhatsApp message from the user. Return JSON:
{
  "intent": "task" | "question" | "thought" | "vent" | "command" | "reflection",
  "entities": {
    "dates": [],
    "people": [],
    "amounts": [],
    "topics": []
  },
  "tools_needed": ["tool_name_1", "tool_name_2"]
}

Intent definitions:
- task: user wants to create, complete, or check a task/reminder
- question: user is asking for information (from Canvas, email, calendar, or general)
- thought: user is sharing an idea, brain dump, or observation to be stored
- vent: user is expressing frustration or emotion (respond empathetically, log mood)
- command: user is giving a direct instruction (send email, create event, log expense)
- reflection: user is responding to a journal/reflection prompt
```

### context_loader
- Based on `intent` and `entities`, pulls relevant context from DB and APIs:
  - Today's calendar events
  - Upcoming deadlines from Canvas (next 7 days)
  - Current task list (pending items)
  - Recent mood scores (last 7 days)
  - Unread email count
  - Relevant memory facts (semantic search via pgvector)
- Sets `user_context` in state

### tool_executor
- Based on `intent` and `entities.tools_needed`, calls the appropriate tools
- May chain multiple tools (e.g., check Canvas → find free slot → create calendar event)
- Stores all results in `tool_results`
- Uses Claude with tool-calling for complex multi-step operations

### response_composer
- Takes `tool_results`, `user_context`, `intent`, and conversation history
- Uses Claude to generate a natural, personalized WhatsApp response
- Adapts tone based on: time of day, recent mood scores, user's communication style
- Formats for WhatsApp: *bold*, _italic_, emojis (moderate), concise by default
- Sets `response` in state

**System prompt for composer:**
```
You are Aura, a WhatsApp life assistant. You're like a sharp, caring friend
with perfect memory and access to all the user's systems.

Personality: casual but competent, supportive but not sycophantic, proactive
but not annoying. Mirror the user's communication style.

Tone rules:
- Morning: energetic, focused
- Afternoon: supportive, productive
- Evening: warm, reflective
- Low mood (score < 4 for 2+ days): gentler, less task pressure
- High mood (score > 7): celebratory, reinforce positive patterns

Format for WhatsApp:
- Use *bold* for emphasis
- Use emojis sparingly and contextually
- Keep messages concise (under 300 words unless asked for detail)
- Use line breaks for readability
```

### memory_writer
- Extracts key facts/preferences/patterns from the conversation
- Generates embeddings and stores in `memory_facts` table via pgvector
- Examples: "user prefers studying at night", "user's favorite food is ramen", "user is stressed about CS midterm"
- Sends the final `response` to WhatsApp via the send message utility

---

## 7. Database Models

```python
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector
from datetime import datetime

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)  # UUID
    phone = Column(String, unique=True, nullable=False)
    name = Column(String)
    timezone = Column(String, default="UTC")
    wake_time = Column(String, default="08:00")  # HH:MM
    sleep_time = Column(String, default="23:00")
    reminder_frequency = Column(String, default="normal")  # low, normal, high
    tone_preference = Column(String, default="casual")  # casual, balanced, formal
    onboarding_complete = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)  # canvas, google, microsoft
    access_token = Column(Text, nullable=False)  # encrypted
    refresh_token = Column(Text)
    expires_at = Column(DateTime)
    scopes = Column(Text)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    source = Column(String, default="manual")  # manual, canvas, email
    source_id = Column(String)  # external ID from Canvas etc.
    due_date = Column(DateTime)
    priority = Column(Integer, default=2)  # 1=high, 2=medium, 3=low
    status = Column(String, default="pending")  # pending, done, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    entry_type = Column(String, nullable=False)  # reflection, gratitude, brain_dump, vent
    content = Column(Text, nullable=False)
    mood_score = Column(Integer)  # 1-10
    embedding = Column(Vector(1536))  # for semantic search
    created_at = Column(DateTime, default=datetime.utcnow)

class VoiceNote(Base):
    __tablename__ = "voice_notes"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    audio_url = Column(String, nullable=False)  # R2/S3 URL
    duration_seconds = Column(Integer)
    transcript = Column(Text)
    summary = Column(Text)  # AI-generated summary for long notes
    tags = Column(JSON)  # ["project", "idea", "meeting"]
    intent = Column(String)  # thought, task, vent, etc.
    embedding = Column(Vector(1536))
    created_at = Column(DateTime, default=datetime.utcnow)

class MoodLog(Base):
    __tablename__ = "mood_logs"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    score = Column(Integer, nullable=False)  # 1-10
    note = Column(Text)
    source = Column(String, default="manual")  # manual, reflection, inferred
    created_at = Column(DateTime, default=datetime.utcnow)

class Expense(Base):
    __tablename__ = "expenses"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    category = Column(String)  # food, transport, entertainment, etc.
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Habit(Base):
    __tablename__ = "habits"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    target_frequency = Column(String, default="daily")  # daily, weekly
    current_streak = Column(Integer, default=0)
    longest_streak = Column(Integer, default=0)
    last_logged = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

class MemoryFact(Base):
    __tablename__ = "memory_facts"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    fact = Column(Text, nullable=False)
    category = Column(String)  # preference, pattern, context, relationship
    confidence = Column(Float, default=0.8)
    embedding = Column(Vector(1536))
    source_message_id = Column(String)  # which conversation this came from
    created_at = Column(DateTime, default=datetime.utcnow)
    last_referenced = Column(DateTime)
```

---

## 8. Tool Definitions

Each tool is a LangChain `@tool` that Claude can call via the tool_executor node.

### Canvas Tools

```python
@tool
def get_canvas_assignments(user_id: str, days_ahead: int = 7) -> list[dict]:
    """Get upcoming assignments from Canvas LMS.
    Returns list of {title, course, due_date, points, submitted}."""

@tool
def get_canvas_grades(user_id: str, course_id: str = None) -> list[dict]:
    """Get recent grades from Canvas.
    Returns list of {assignment, course, score, points_possible, feedback}."""
```

### Email Tools

```python
@tool
def get_emails(user_id: str, count: int = 10, filter: str = "unread") -> list[dict]:
    """Get emails from Gmail/Outlook.
    filter: 'unread', 'important', 'all'
    Returns list of {id, from, subject, preview, date, is_important}."""

@tool
def send_email(user_id: str, to: str, subject: str, body: str) -> dict:
    """Send an email via Gmail/Outlook.
    Returns {success, message_id}."""

@tool
def reply_to_email(user_id: str, email_id: str, body: str) -> dict:
    """Reply to a specific email.
    Returns {success, message_id}."""
```

### Calendar Tools

```python
@tool
def get_calendar_events(user_id: str, date: str = "today", days: int = 1) -> list[dict]:
    """Get calendar events. date format: 'today', 'tomorrow', or 'YYYY-MM-DD'.
    Returns list of {title, start, end, location, description}."""

@tool
def create_calendar_event(user_id: str, title: str, start: str, end: str, description: str = "") -> dict:
    """Create a calendar event. start/end in ISO format.
    Returns {success, event_id, link}."""

@tool
def find_free_slots(user_id: str, date: str = "today", min_duration_minutes: int = 60) -> list[dict]:
    """Find free time slots in the user's calendar.
    Returns list of {start, end, duration_minutes}."""
```

### Task Tools

```python
@tool
def create_task(user_id: str, title: str, due_date: str = None, priority: int = 2) -> dict:
    """Create a new task. priority: 1=high, 2=medium, 3=low.
    Returns {id, title, due_date, priority}."""

@tool
def get_tasks(user_id: str, status: str = "pending") -> list[dict]:
    """Get tasks. status: 'pending', 'done', 'all'.
    Returns list of {id, title, due_date, priority, status}."""

@tool
def complete_task(user_id: str, task_id: str) -> dict:
    """Mark a task as completed.
    Returns {success, streak_info}."""
```

### Journal & Mood Tools

```python
@tool
def save_journal_entry(user_id: str, entry_type: str, content: str, mood_score: int = None) -> dict:
    """Save a journal entry. entry_type: reflection, gratitude, brain_dump, vent.
    Returns {id, entry_type, mood_score}."""

@tool
def log_mood(user_id: str, score: int, note: str = "") -> dict:
    """Log mood score (1-10).
    Returns {score, trend (last 7 days), streak}."""

@tool
def get_mood_history(user_id: str, days: int = 7) -> list[dict]:
    """Get mood history.
    Returns list of {score, note, date} + average."""
```

### Voice Note Tools

```python
@tool
def search_voice_notes(user_id: str, query: str) -> list[dict]:
    """Semantic search over past voice notes.
    Returns list of {id, transcript_preview, date, tags, audio_url}."""

@tool
def get_voice_note_summary(user_id: str, voice_note_id: str) -> dict:
    """Get full transcript and summary of a voice note.
    Returns {transcript, summary, tags, date, duration}."""
```

### Expense Tools

```python
@tool
def log_expense(user_id: str, amount: float, category: str, description: str = "") -> dict:
    """Log an expense.
    Returns {id, amount, category, weekly_total, budget_remaining}."""

@tool
def get_expense_summary(user_id: str, period: str = "week") -> dict:
    """Get expense summary. period: 'week', 'month'.
    Returns {total, by_category, comparison_to_last_period}."""
```

### Memory Tools

```python
@tool
def search_memory(user_id: str, query: str) -> list[dict]:
    """Semantic search over stored user facts and context.
    Returns list of {fact, category, confidence, date}."""

@tool
def get_user_context(user_id: str) -> dict:
    """Get comprehensive user context for personalization.
    Returns {recent_mood, pending_tasks, upcoming_deadlines, recent_topics, patterns}."""
```

---

## 9. WhatsApp Integration

### Webhook Setup (api/webhook.py)

```python
from fastapi import APIRouter, Request, Response

router = APIRouter()

@router.get("/webhook")
async def verify_webhook(hub_mode: str = None, hub_verify_token: str = None, hub_challenge: str = None):
    """WhatsApp webhook verification."""
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)

@router.post("/webhook")
async def receive_message(request: Request):
    """Process incoming WhatsApp messages."""
    body = await request.json()
    # Extract message from webhook payload
    # Run through LangGraph agent
    # Response is sent by memory_writer node
    return Response(status_code=200)
```

### Message Sending (tools/whatsapp.py)

```python
import httpx

async def send_whatsapp_message(to: str, text: str):
    """Send a text message via WhatsApp Business API."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text}
            }
        )

async def send_whatsapp_template(to: str, template_name: str, params: list[str]):
    """Send a template message (for proactive outreach)."""
    # Template messages are needed for messages outside the 24h window
    pass

async def download_media(media_id: str) -> bytes:
    """Download media (voice notes, images) from WhatsApp."""
    async with httpx.AsyncClient() as client:
        # First get the media URL
        resp = await client.get(
            f"https://graph.facebook.com/v18.0/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        )
        media_url = resp.json()["url"]
        # Then download the actual file
        media_resp = await client.get(media_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"})
        return media_resp.content
```

---

## 10. Environment Variables

```env
# Core
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/aura
REDIS_URL=redis://localhost:6379

# WhatsApp
WHATSAPP_TOKEN=EAAx...
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_VERIFY_TOKEN=your-verify-token

# OAuth - Canvas
CANVAS_BASE_URL=https://your-school.instructure.com
CANVAS_CLIENT_ID=...
CANVAS_CLIENT_SECRET=...

# OAuth - Google (Gmail + Calendar)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://your-domain.com/auth/google/callback

# Transcription
DEEPGRAM_API_KEY=...
# OR
OPENAI_API_KEY=sk-...  # for Whisper

# File Storage
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=aura-voice-notes
R2_ENDPOINT_URL=https://{account_id}.r2.cloudflarestorage.com
```

---

## 11. Dependencies

```toml
[project]
name = "aura"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    # Agent framework
    "langgraph>=0.2.0",
    "langchain-anthropic>=0.3.0",
    "langchain-core>=0.3.0",

    # API server
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",

    # Database
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "pgvector>=0.3.0",

    # Cache
    "redis>=5.0.0",
    "langgraph-checkpoint-redis>=0.1.0",

    # HTTP
    "httpx>=0.27.0",

    # Transcription
    "deepgram-sdk>=3.0.0",

    # File storage
    "boto3>=1.35.0",

    # Scheduling
    "apscheduler>=3.10.0",

    # Config
    "pydantic-settings>=2.0.0",

    # Auth
    "authlib>=1.3.0",
    "cryptography>=42.0.0",
]
```

---

## 12. Docker Compose

```yaml
version: "3.8"
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - db
      - redis
    volumes:
      - .:/app

  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: aura
      POSTGRES_PASSWORD: aura
      POSTGRES_DB: aura
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

---

## 13. Features

### 13.1 Canvas LMS
- Pull upcoming assignments, quizzes, exams with due dates and point values
- Morning briefing with days remaining per assignment
- Deadline warnings at 72h, 24h, 3h (escalating urgency)
- Grade notifications when new grades are posted
- Study block suggestions based on free calendar slots before exams

### 13.2 Email (Gmail / Outlook)
- Morning digest: unread count + summaries of important emails
- Reply from WhatsApp: "Reply to Prof Chen saying I'll submit by Friday" → drafts and sends
- Email triage: categorize as urgent, FYI, promotional, action-needed
- Follow-up tracking: "You emailed the TA 3 days ago with no reply — follow up?"
- Smart compose: "Draft an email to my group about the meeting" → generates for approval

### 13.3 Calendar
- Schedule awareness: all reminders respect calendar (no nudges during class)
- Daily schedule in morning briefing
- Quick event creation via natural language
- Conflict detection when creating events
- Free time analysis: find gaps and suggest productive uses

### 13.4 Voice Notes
- Auto-transcription of every voice note via Whisper/Deepgram
- Intent classification: thought, task, idea, vent, meeting notes, brain dump
- Auto-tagging by content (project names, people, topics)
- Summary generation for voice notes > 2 minutes
- Semantic search: "What did I say about that startup idea last week?"
- Time-based retrieval: "Play my voice notes from Tuesday"
- Cross-reference: voice note content surfaces in relevant contexts

### 13.5 Health & Wellbeing
- Water reminders every 2h during waking hours (calendar-aware)
- Meal reminders for breakfast, lunch, dinner (adaptive timing)
- Sleep prompts at user's bedtime
- Sedentary alerts: "You've been sitting for 3 hours"
- Optional Apple Health / Google Fit integration

### 13.6 Reflection & Journaling
- **Nightly check-in:** "What made today worth it?", "Rate your day 1-10", "One thing you'd change?"
- Adaptive flow: supportive if mood is low, celebratory if mood is high
- **Weekly recap:** tasks completed, mood trend, habits, voice note highlights
- **Monthly review:** comprehensive stats, pattern insights, longer reflection prompts
- Gratitude prompts (optional, morning or evening)

### 13.7 Task Management
- Natural language task creation with due date extraction
- Canvas auto-import as tasks
- Email action item extraction
- AI-powered priority scoring
- Daily task list in morning briefing
- Completion tracking with streak celebration

### 13.8 Expense Tracking
- Quick logging: "Spent $15 on lunch" → auto-categorized
- Weekly spending summary by category
- Budget alerts at 80% threshold
- Subscription reminders before renewals
- CSV export on request

### 13.9 Social & Networking
- Birthday reminders
- Follow-up nudges: "You said you'd text Alex back — did you?"
- Networking logger: log new contacts with auto follow-up reminders
- Relationship maintenance: surface contacts you haven't reached out to

---

## 14. Conversation Design

### Personality
Aura is like a sharp, caring friend with perfect memory. Casual but competent, supportive but not sycophantic, proactive but not annoying. Mirrors the user's communication style.

### Tone by Time
- **Morning:** energetic, focused ("Good morning! Here's your day:")
- **Afternoon:** supportive ("You're crushing it — 2 tasks down, 1 to go")
- **Evening:** warm, reflective ("How was your day? Let's check in.")
- **Low mood (2+ days):** gentler, less pressure ("Hey, no pressure today.")

### WhatsApp Formatting
- Use *bold* for emphasis
- Emojis: moderate, contextual, mirror user's style
- Length: concise by default, detailed when asked
- Line breaks for readability

---

## 15. Onboarding Flow

All in WhatsApp, under 5 minutes:

1. **Welcome** → collect name
2. **Timezone** → detect from phone number or ask
3. **Integrations** → send OAuth links for Canvas, Gmail, Calendar (can skip)
4. **Preferences** → wake time, sleep time, reminder frequency
5. **Demo** → show sample morning briefing + nightly check-in
6. **Activate** → schedule first morning briefing

---

## 16. Development Phases

### Phase 1: Foundation (Week 1)
- [ ] FastAPI server with WhatsApp webhook verification + message echo
- [ ] Docker Compose (PostgreSQL + Redis)
- [ ] SQLAlchemy models + Alembic migrations
- [ ] Basic LangGraph graph: ingress → classifier → composer
- [ ] Claude integration for natural conversation (no tools)
- [ ] WhatsApp send message utility
- **Test:** Send a WhatsApp message, get a Claude-powered response back

### Phase 2: Core Tools (Week 2)
- [ ] Voice note download + transcription pipeline
- [ ] Task CRUD tools
- [ ] Mood logging + journal entry tools
- [ ] Expense tracking tool
- [ ] Basic memory system (fact extraction + storage)
- **Test:** Create tasks, log mood, send voice notes — all via WhatsApp

### Phase 3: Integrations (Week 3)
- [ ] Canvas OAuth + assignment/grade fetching
- [ ] Google OAuth + Gmail read/send
- [ ] Google Calendar read/write
- [ ] Context loader combining all data sources
- [ ] pgvector semantic search over voice notes + memory
- **Test:** "What's due this week?" pulls real Canvas data

### Phase 4: Proactive System (Week 4)
- [ ] APScheduler with per-user timezone-aware jobs
- [ ] Morning briefing generation + delivery
- [ ] Water/meal/movement reminders (calendar-aware)
- [ ] Nightly reflection flow with adaptive prompts
- [ ] Deadline warning system (72h, 24h, 3h)
- **Test:** Receive unprompted reminders at correct times

### Phase 5: Intelligence (Week 5+)
- [ ] Weekly recap generation
- [ ] Pattern detection + adaptive behavior
- [ ] Tone adaptation based on mood history
- [ ] Cross-integration intelligence (smart suggestions)
- [ ] Onboarding flow
- [ ] Error handling + retry logic + graceful degradation
- **Test:** Bot feels personalized and contextually aware

---

## 17. Security

- All OAuth tokens encrypted at rest (Fernet/AES)
- Auto token refresh; expired tokens trigger re-auth via WhatsApp
- Voice note audio deleted after configurable retention (default 90 days)
- User can request data export or full deletion via WhatsApp
- Webhook signature verification on all incoming messages
- Rate limiting on API endpoints
- Per-user state isolation (all queries scoped to user_id)

---

## 18. Success Metrics

| Metric | Month 1 | Month 3 |
|---|---|---|
| Daily Active Users | 10 beta | 100+ |
| Messages per user/day | 5+ | 10+ |
| Nightly reflection rate | 40% | 65% |
| Task completion rate | 50% | 70% |
| Response latency | < 5s | < 3s |
| 7-day retention | 60% | 75% |

---

## 19. Future Roadmap

- Telegram + iMessage support
- Spotify integration (mood playlists, study music)
- Notion two-way sync
- Group accountability (shared habit challenges)
- AI-generated weekly PDF reports with charts
- Web dashboard for journal/mood/analytics browsing
- Apple Watch companion
- University-specific features (course registration, prof ratings)
- Bank API integration for auto expense categorization
- Pomodoro mode via WhatsApp