# Aura — Donna on WhatsApp

A WhatsApp AI assistant for NUS students. She manages your calendar, deadlines, tasks, moods, expenses, and habits — and texts you before you forget.

**WhatsApp:** +65 8338 3940
**Landing page:** [getdonna.co](https://getdonna.co)

---

## Getting Started

### 1. Say hi

Text the number above on WhatsApp. Donna walks you through setup in under 2 minutes:

```
Donna: Hi. I'm Donna. What's your name?
You:   Adi
Donna: Adi. Where are you based?
You:   Singapore
Donna: Singapore. When do you start and end your day? (e.g. 7am–midnight)
You:   8am to midnight
Donna: What year and major are you? (e.g. "Y2 CS", "year 3 biz")
You:   Y2 CS
Donna: Done, Adi. Tasks, mood, expenses, memory — ready.
```

After setup, Donna offers three integration buttons:

| Integration | What it unlocks |
|---|---|
| **Connect Canvas** | Deadline warnings, grade alerts, assignment tracking |
| **Connect Google** | Calendar events, email triage, free slot detection |
| **Connect Outlook** | Same as Google, for Microsoft users |

All integrations are optional. Donna works without them — she just knows less.

### 2. Share your NUSMods timetable

Go to NUSMods, click "Share/Export", copy the URL, and send it to Donna:

```
You: here's my timetable https://nusmods.com/timetable/sem-2/share?CS2103T=TUT:08,LEC:G17&IS1108=...
```

She'll parse your modules and add them to your calendar.

---

## What You Can Do

Everything is natural language. No commands, no menus, no forms.

### Tasks

```
You:   remind me to submit CS2103 by friday 11:59pm
You:   what's on my plate?
You:   done with the MA2001 practice set
```

### Mood

```
You:   feeling kinda off today, like a 4
You:   mood's an 8, good lecture today
```

Donna tracks your mood over time and adjusts her tone — gentler when you're low, lighter when you're up.

### Expenses

```
You:   spent 8.50 on lunch at deck
You:   how much did I spend this week?
```

### Journaling

```
You:   brain dump: feeling overwhelmed with 3 deadlines + group project drama
You:   grateful for noor helping with the IS1108 slides today
```

You can also send voice notes — Donna transcribes and processes them like text.

### Calendar

```
You:   what's my schedule tomorrow?
You:   when am I free this week?
You:   create an event: study session 3-5pm thursday
```

### Email

```
You:   any important emails?
You:   reply to prof tan saying i'll submit by friday
```

### Memory

```
You:   that ramen place near PGP is called Menya Kanae
You:   noor's birthday is march 15
```

Donna remembers everything you tell her — people, places, preferences, dates — and brings them up when relevant.

### Habits

```
You:   I went running today
You:   did I go to the gym this week?
```

---

## What Donna Does on Her Own

Donna doesn't just wait for you to text. She checks your signals every 5 minutes and messages you when something is worth saying. She stays silent most of the time — that's the point.

### Message Types

| Category | Example |
|---|---|
| **Deadline warning** | "CS2103 Assignment 3 due tomorrow 11:59pm. You're free 3-5 today." |
| **Schedule info** | "Your 2pm got moved to 3pm. Same room." |
| **Task reminder** | "That MA2001 practice set you added yesterday — still on the list." |
| **Briefing** | "Wednesday. CS2103 10-12, IS1108 tutorial at 3. MA2001 due Friday." |
| **Email alert** | "Prof Tan emailed about the CS2103 submission format change." |
| **Grade alert** | "MA2001 midterm: 78/100. Above average based on past semesters." |
| **Wellbeing** | "Busy week. The MA2001 practice set isn't graded — could push it to the weekend?" |
| **Habit** | "Day 14 of running. Two weeks. Not bad." |
| **Memory recall** | "That ramen place you mentioned — Noor was interested too. Free Saturday." |
| **Social** | "Noor's birthday is Saturday — just flagging in case you want to plan something." |

### Guardrails

- **Quiet hours**: She won't text between your sleep time and wake time (unless it's urgent).
- **Daily cap**: Max 5 messages per day (fewer when you're new).
- **Cooldown**: At least 30 minutes between messages.
- **No spam**: If she already told you something, she won't repeat it.
- **Reads the room**: If you ignore a category of messages, she sends fewer. If you engage, she sends more.

### Trust Ramp

Donna starts conservative and increases proactiveness as you interact:

| Level | When | Daily cap | What she sends |
|---|---|---|---|
| **New** | First 2 weeks | 2/day | Only urgent deadlines |
| **Building** | 2-4 weeks | 3/day | Schedule + deadlines |
| **Established** | 1-3 months | 4/day | Full range including wellbeing |
| **Deep** | 3+ months | 5/day | Social, subtle patterns, full personality |

If you stop using Donna for 30+ days, she backs off one level. 60+ days, two levels. She re-escalates when you come back.

---

## Giving Donna Feedback

You don't need to do anything special. Donna reads your responses:

- **Engage** with a message (reply, tap a button) and she learns that category works for you.
- **Ignore** a message and she learns to send fewer like it.
- **Say "stop sending me X"** and she'll suppress that category entirely.
- **Say "more deadline reminders"** and she'll prioritize them.

---

## Privacy

- All data is encrypted at rest.
- Donna never shares your data or uses it for model training.
- OAuth tokens for Google/Microsoft/Canvas are stored securely and only used to read your data.
- Voice notes are transcribed and stored — the audio is kept in encrypted cloud storage.

---

## For Developers

### Architecture

```
WhatsApp → POST /webhook → LangGraph agent pipeline → WhatsApp reply
                           ↕
                    APScheduler (5min) → Donna proactive loop → WhatsApp
```

**Reactive path** (user messages):
Ingress → Classifier → Context → Planner (ReAct loop) → Tool Executor → Composer → Memory Writer

**Proactive path** (Donna-initiated):
Signal collectors → Context builder → LLM candidate generator → Scorer/filter → Validator → Sender

### Stack

- **Backend**: FastAPI + LangGraph + SQLAlchemy async (PostgreSQL + pgvector)
- **LLM**: GPT-4o (via langchain-openai)
- **Integrations**: Composio (Google/Microsoft OAuth), Canvas (PAT), Deepgram (transcription)
- **Hosting**: Railway
- **Landing page**: Next.js + Tailwind

### Running Locally

```bash
# Install
cd app
pip install -e ".[dev]"

# Configure
cp .env.example .env   # fill in all keys

# Run
uvicorn api.main:app --reload

# Test
pytest tests/ -v --asyncio-mode=auto

# Lint
ruff check . --target-version py311 --line-length 100
```

### Required Environment Variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | GPT-4o for all LLM calls |
| `DATABASE_URL` | PostgreSQL (asyncpg pooler) |
| `DATABASE_URL_DIRECT` | PostgreSQL (psycopg direct, for LangGraph checkpointer) |
| `WHATSAPP_TOKEN` | Meta Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp Business phone number ID |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verification token |
| `CANVAS_BASE_URL` | Canvas instance URL (e.g. `https://canvas.nus.edu.sg`) |
| `COMPOSIO_API_KEY` | Composio SDK key for OAuth flows |
| `COMPOSIO_GMAIL_AUTH_CONFIG_ID` | Gmail OAuth config |
| `COMPOSIO_GCAL_AUTH_CONFIG_ID` | Google Calendar OAuth config |
| `COMPOSIO_OUTLOOK_AUTH_CONFIG_ID` | Microsoft OAuth config |
| `DEEPGRAM_API_KEY` | Voice note transcription |
| `R2_ACCOUNT_ID` | Cloudflare R2 (voice note storage) |
| `R2_ACCESS_KEY_ID` | R2 access key |
| `R2_SECRET_ACCESS_KEY` | R2 secret |
| `R2_BUCKET_NAME` | R2 bucket name |

### Test Coverage

232 tests across the full system:

| Area | Tests | What's covered |
|---|---|---|
| Proactive brain | 76 | Scoring, filtering, suppression, exploration, trust, dedup, prefilter, feedback, metrics, voice, template filling, sending, validators |
| Signals | 18 | Internal signals, dedup, enrichment |
| Memory | 11 | Entity store, recall, embeddings |
| Full loop | 8 | End-to-end Donna scenarios (deadline, quiet hours, cooldown, briefing, memory recall, mood) |
| Reflection | 2 | Nightly behavior computation |
| User model | 2 | Full snapshot, missing user |
| Delivery | 13 | Deferred sends, delivery status tracking |
| WhatsApp | 9 | Response parsing, client lifecycle |
| **Total** | **232** | |

```bash
pytest tests/ -v --asyncio-mode=auto
```
