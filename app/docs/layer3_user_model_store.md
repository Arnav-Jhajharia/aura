# Layer 3: User Model Store — Architecture & Implementation Plan

> **What Layer 3 does**: Maintains a rich, evolving model of each user — who they are, what they care about, how they behave, what they respond to — so that every other layer can make personalized decisions instead of generic ones.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Current State Audit](#2-current-state-audit)
3. [Target Architecture](#3-target-architecture)
4. [The Four Pillars](#4-the-four-pillars)
   - 4.1 Static Profile
   - 4.2 Memory System
   - 4.3 Behavioral Model
   - 4.4 Preference Learning
5. [Data Model Changes](#5-data-model-changes)
6. [Implementation Plan](#6-implementation-plan)
7. [How Other Layers Consume the User Model](#7-how-other-layers-consume-the-user-model)

---

## 1. The Problem

Right now, Donna knows almost nothing about her users beyond a name, timezone, and a bag of unstructured memory facts. She treats a first-year CS student the same as a fourth-year business major. She doesn't know that one user ignores wellbeing messages on weekdays, that another always procrastinates until the last 6 hours, or that a third user hates being reminded about things they've already started working on.

The research is clear: timing accounts for 40% of variance in intervention acceptance (ComPeer), and unsolicited help triggers self-threat (Harari & Amir). Both of these require knowing the user deeply — not just their schedule, but their rhythms, sensitivities, and track record with Donna.

**What we have**: A flat `User` table with 6 preference fields, a `MemoryFact` table that's a catch-all text dump, and a `ProactiveFeedback` table that's brand new.

**What we need**: A structured, queryable user model that evolves with every interaction and directly drives Layer 1 (signal urgency), Layer 2 (message generation, trust ramp, scoring), Layer 4 (message style), and Layer 5 (delivery timing).

---

## 2. Current State Audit

### What exists and where it lives:

#### `User` model (db/models.py)

The static profile. Created at first message, populated during onboarding.

| Field | Type | Set During | Used By |
|---|---|---|---|
| `name` | String | Onboarding step 1 | Composer (greeting), candidates prompt |
| `timezone` | String | Onboarding step 2 | Prefilter (quiet hours), signal collectors (timezone fix) |
| `wake_time` | String | Onboarding step 3 | Prefilter (quiet hours), internal signals (morning window) |
| `sleep_time` | String | Onboarding step 3 | Prefilter (quiet hours), internal signals (evening window) |
| `reminder_frequency` | String | Onboarding step 3 | **Not used anywhere** |
| `tone_preference` | String | Onboarding step 3 | context_loader passes it, composer prompt **doesn't read it** |
| `onboarding_complete` | Bool | End of onboarding | Scheduler (only loop onboarded users) |
| `onboarding_step` | String | Onboarding flow | Graph routing (onboarding vs main pipeline) |
| `pending_action` | String | Auth flows | Graph routing (token collector) |
| `created_at` | DateTime | Auto | Trust level computation (days_active) |

**Verdict**: Bare minimum. `reminder_frequency` is collected but never used. `tone_preference` is collected but never reaches the composer prompt. No academic info (year, major, faculty). No evolving preferences.

#### `MemoryFact` model (db/models.py)

The memory system. Stores extracted facts from conversations + entities + patterns.

| Field | Type | Purpose |
|---|---|---|
| `fact` | Text | The actual fact string (freeform) |
| `category` | String | Loosely typed: "preference", "pattern", "context", "relationship", "entity:person", "entity:place", etc. |
| `confidence` | Float | Set to 0.7 (entities) or 0.8 (default) or variable (patterns) — **never decayed or updated** |
| `embedding` | Vector(1536) | Exists but **never populated** — recall uses ILIKE keyword search |
| `source_message_id` | String | Exists but **never set** |
| `last_referenced` | DateTime | Updated when recall finds this fact |

**Verdict**: The MemoryFact table is doing too many jobs. It stores entities, patterns, preferences, timetable data, and raw contextual facts all in one freeform text column. No structured querying possible — everything goes through ILIKE keyword search. The `embedding` column is the biggest missed opportunity: pgvector is installed, the column exists, but nothing populates or queries it.

#### Memory subsystem (`donna/memory/`)

Three files, three LLM calls per user message:

| File | What it does | When it runs | LLM model |
|---|---|---|---|
| `entities.py` | Extracts people, places, tasks, events, preferences from user message | Every user message (via `memory_writer` node) | GPT-4o |
| `patterns.py` | Detects behavioral patterns from chat history + memory facts | **Never called automatically** — function exists but no trigger | GPT-4o |
| `recall.py` | Generates search keywords → ILIKE search on MemoryFact | Every Donna proactive cycle (via `build_context`) | GPT-4o |

**Problems:**
1. `entities.py` runs on every single message, even "lol ok" (it does check `len < 3`, but "sure" passes). At GPT-4o, that's ~$0.003/message just for entity extraction.
2. `patterns.py` is never scheduled. The function exists but nothing calls it. Patterns only get stored if someone manually calls `detect_patterns()`.
3. `recall.py` uses ILIKE keyword search, which misses semantic connections ("I love sushi" won't match a search for "restaurant"). The Vector(1536) column exists specifically for semantic search but isn't used.
4. Memory facts accumulate forever with no cleanup, decay, or consolidation. A user active for 6 months could have thousands of facts, most stale.

#### `ProactiveFeedback` model (db/models.py) — NEW

Recently built. Tracks engagement with proactive messages.

| Field | Purpose | Status |
|---|---|---|
| `outcome` | engaged / ignored / pending / negative / button_click | Working (check_and_update_feedback in memory_writer) |
| `response_latency_seconds` | Time to respond | Working |
| `category` | What type of message | Working |
| `trigger_signals` | Which signals caused it | Working |

**Verdict**: Good foundation. Already wired into feedback.py → context.py → candidates.py prompt. The data is there; the question is how to use it more deeply.

#### Trust system (`donna/brain/trust.py`) — NEW

Computes trust level from days_active + total_interactions. Returns level + config (score_threshold, daily_cap, min_urgency).

**Verdict**: Working but simplistic. Only uses time + message count. Doesn't factor in feedback data (engagement rate), integration depth (how many services connected), or content depth (journal entries, mood logs, etc.).

#### Reactive context (`agent/nodes/context.py`)

Loads context for the reactive pipeline (when user messages Donna). Pulls: connected integrations, pending tasks, recent moods, upcoming deadlines, today's spending, conversation history, memory facts, deferred insights.

**Verdict**: Kitchen-sink query that loads everything regardless of intent. A user asking "what time is it" triggers the same 8 DB queries as "what's due this week." No user model awareness — doesn't know user preferences, patterns, or feedback history.

---

## 3. Target Architecture

The User Model Store is not a single table — it's a **structured view** composed of four pillars, each with its own storage and update mechanism:

```
┌───────────────────────────────────────────────────────────────┐
│                     USER MODEL STORE                          │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐  │
│  │   STATIC    │  │   MEMORY    │  │    BEHAVIORAL        │  │
│  │   PROFILE   │  │   SYSTEM    │  │    MODEL             │  │
│  │             │  │             │  │                      │  │
│  │ name        │  │ entities    │  │ activity_hours       │  │
│  │ timezone    │  │ preferences │  │ response_patterns    │  │
│  │ year/major  │  │ facts       │  │ procrastination_idx  │  │
│  │ wake/sleep  │  │ embeddings  │  │ message_preferences  │  │
│  │ integrations│  │ (pgvector)  │  │ engagement_rates     │  │
│  │             │  │             │  │ signal_sensitivities │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬───────────┘  │
│         │                │                     │              │
│  ┌──────┴────────────────┴─────────────────────┴───────────┐  │
│  │                PREFERENCE LEARNING                       │  │
│  │                                                          │  │
│  │  Feedback loop: track outcomes → update weights          │  │
│  │  Nightly reflection: consolidate patterns + decay stale  │  │
│  │  Exports: user_snapshot() → single dict for any layer    │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

**Key principle**: The User Model Store is a **read-heavy, write-occasionally** system. It doesn't need to update on every message. It consolidates at natural boundaries (nightly, weekly) and exposes a single `get_user_snapshot()` function that any layer can call.

---

## 4. The Four Pillars

### 4.1 Static Profile

**What it is**: Explicit information the user tells us or we can directly observe. Doesn't change often.

**Current state**: The `User` table has name, timezone, wake/sleep times, reminder_frequency, tone_preference. That's it.

**What to add to `User` model:**

```python
# Academic context (set during onboarding or inferred)
academic_year = Column(Integer, nullable=True)      # 1, 2, 3, 4, 5 (grad)
faculty = Column(String, nullable=True)             # "Computing", "Business", "Engineering", etc.
major = Column(String, nullable=True)               # "Computer Science", "Information Systems"
graduation_year = Column(Integer, nullable=True)    # 2027

# Integration status (denormalized for fast access)
has_canvas = Column(Boolean, default=False)
has_google = Column(Boolean, default=False)
has_microsoft = Column(Boolean, default=False)
nusmods_imported = Column(Boolean, default=False)

# Engagement metrics (updated nightly by reflection job)
total_messages = Column(Integer, default=0)
proactive_engagement_rate = Column(Float, default=0.5)  # rolling 30-day
avg_response_latency_seconds = Column(Float, nullable=True)
last_active_at = Column(DateTime, nullable=True)
```

**How academic context helps**: A CS student getting a `CANVAS_GRADE_POSTED` for a coding assignment means something different than a business student getting a grade on a presentation. A first-year student needs more hand-holding than a final-year student. Faculty/major also helps Donna understand which modules are "core" vs. elective.

**Onboarding additions**: After the current 4-step flow (name → timezone → schedule → connect), add an optional step: "What year are you in? And what are you studying?" This can be a conversational exchange, not a form.

---

### 4.2 Memory System

**What it is**: Everything Donna remembers about the user from conversations — people, places, preferences, events, facts.

**Current state**: `MemoryFact` with freeform text, ILIKE search, unused pgvector column.

**Target architecture for memory:**

#### A. Structured entity storage

Instead of jamming everything into `MemoryFact.fact` as freeform text, separate entities into a proper table:

```python
class UserEntity(Base):
    __tablename__ = "user_entities"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "name_normalized",
                         name="uq_user_entity"),
        Index("ix_user_entity_lookup", "user_id", "entity_type"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    entity_type = Column(String, nullable=False)  # person, place, course, food, hobby, event
    name = Column(String, nullable=False)          # "Noor", "that ramen place near PGP"
    name_normalized = Column(String, nullable=False)  # lowercase, trimmed for dedup

    # Structured metadata (varies by type)
    metadata = Column(JSON, default=dict)
    # person: {relationship: "friend", faculty: "computing", birthday: "Feb 20"}
    # place:  {type: "restaurant", location: "near PGP", visited: true}
    # course: {code: "CS2103", semester: "AY24/25 S2", grade: null}
    # food:   {sentiment: "loves", dietary: null}
    # hobby:  {frequency: "weekly", last_mentioned: "2025-02-10"}

    sentiment = Column(String, nullable=True)      # positive, negative, neutral, mixed
    mention_count = Column(Integer, default=1)
    first_mentioned = Column(DateTime, default=datetime.utcnow)
    last_mentioned = Column(DateTime, default=datetime.utcnow)
    source_message_ids = Column(JSON, default=list)  # track which messages mentioned this
```

**Why this is better than MemoryFact for entities:**
- Queryable by type: "get all people this user has mentioned"
- Dedup by normalized name: no more duplicate "Noor" / "noor" / "Noor's" entries
- `mention_count` tells us importance: a person mentioned 15 times is close; mentioned once is passing
- `metadata` JSON allows structured data per entity type
- `sentiment` tracking: does the user like this thing?

#### B. Keep MemoryFact for unstructured observations

MemoryFact remains the catch-all for things that don't fit entity structure:
- "User tends to study late at night"
- "Mentioned feeling overwhelmed about thesis"
- "Prefers bullet-point summaries over long paragraphs"

But add proper categories and tagging:

**Standardize MemoryFact categories:**
```
preference:communication  — "prefers brief messages"
preference:schedule       — "likes studying after dinner"
preference:academic       — "hates group projects"
preference:food           — "vegetarian"
context:academic          — "struggling with MA2001"
context:social            — "going through a breakup"
context:health            — "has been going to the gym regularly"
relationship:friend       — "close with Noor, they study together"
relationship:family       — "mom's birthday is March 15"
pattern:temporal          — "most active between 9 PM and midnight"
pattern:behavioral        — "procrastinates coding assignments but not essays"
pattern:emotional         — "mood dips on Monday mornings"
```

#### C. Enable pgvector semantic search

The `embedding` column on MemoryFact has been sitting empty since day one. Here's how to activate it:

```python
# In memory_writer (after extracting facts):
from openai import AsyncOpenAI

openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

async def _embed_text(text: str) -> list[float]:
    """Generate embedding for a text string."""
    result = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return result.data[0].embedding

# When storing a MemoryFact:
fact = MemoryFact(
    id=generate_uuid(),
    user_id=user_id,
    fact=fact_text,
    category=category,
    confidence=0.8,
    embedding=await _embed_text(fact_text),  # <-- NEW
)
```

**Cost**: `text-embedding-3-small` is $0.02 per 1M tokens. A fact is ~20 tokens → $0.0000004 per embedding. Effectively free.

**Semantic recall** (replace ILIKE in `recall.py`):
```python
from pgvector.sqlalchemy import Vector
from sqlalchemy import text

async def semantic_recall(user_id: str, query: str, limit: int = 10):
    """Find memory facts semantically similar to query using pgvector."""
    query_embedding = await _embed_text(query)

    async with async_session() as session:
        # pgvector cosine distance operator: <=>
        result = await session.execute(
            text("""
                SELECT id, fact, category, confidence,
                       1 - (embedding <=> :query_vec) AS similarity
                FROM memory_facts
                WHERE user_id = :uid
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> :query_vec
                LIMIT :lim
            """),
            {"query_vec": str(query_embedding), "uid": user_id, "lim": limit},
        )
        return [dict(row._mapping) for row in result.all()]
```

**Impact**: "I love sushi" will now match a recall query for "dinner plans" or "restaurant recommendation." ILIKE would only match if you searched for the exact word "sushi."

---

### 4.3 Behavioral Model

**What it is**: Patterns derived from observation, not from what the user tells us. Updated periodically (nightly), not on every message.

**Current state**: `patterns.py` exists with LLM-based pattern detection but is never called automatically. Patterns are stored as freeform MemoryFact entries with `category="pattern"`.

**Target: Structured `UserBehavior` model**

```python
class UserBehavior(Base):
    __tablename__ = "user_behaviors"
    __table_args__ = (
        UniqueConstraint("user_id", "behavior_key", name="uq_user_behavior"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    behavior_key = Column(String, nullable=False)
    # Keys:
    #   "active_hours"         — when they typically message
    #   "response_speed"       — how fast they reply to Donna
    #   "procrastination_idx"  — how late they start on assignments
    #   "engagement_by_cat"    — which proactive categories they engage with
    #   "message_length_pref"  — do they prefer short or detailed messages
    #   "mood_pattern"         — weekly mood rhythm
    #   "study_pattern"        — when/how they study
    #   "signal_sensitivity"   — which signal types they care about

    value = Column(JSON, nullable=False)
    # Examples:
    # active_hours:        {"peak_hours": [21, 22, 23], "quiet_hours": [2,3,4,5,6,7]}
    # response_speed:      {"median_seconds": 180, "p90_seconds": 900}
    # procrastination_idx: {"avg_hours_before_due": 8.5, "trend": "improving"}
    # engagement_by_cat:   {"deadline_warning": 0.85, "wellbeing": 0.15, ...}
    # message_length_pref: {"avg_user_msg_words": 12, "prefers_brief": true}
    # mood_pattern:        {"monday": 4.2, "tuesday": 5.1, ..., "weekend_avg": 7.0}
    # signal_sensitivity:  {"canvas_deadline": "high", "email_unread": "low", "mood_checkin": "ignore"}

    confidence = Column(Float, default=0.5)
    sample_size = Column(Integer, default=0)     # how many data points this is based on
    last_computed = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Why structured instead of LLM-generated patterns?**

The current `patterns.py` asks GPT-4o to detect patterns from chat history. Problems:
- Expensive ($0.01-0.03 per call)
- Non-deterministic (different patterns each run)
- Not queryable ("does this user procrastinate?" requires re-running the LLM)
- No confidence tracking or sample size

Structured behaviors are computed deterministically from data. The LLM can still generate qualitative pattern descriptions for the composer prompt, but the hard behavioral data should be computed, not hallucinated.

**Computation functions (run nightly):**

```python
async def compute_active_hours(user_id: str) -> dict:
    """Analyze message timestamps to find peak activity hours."""
    async with async_session() as session:
        messages = await session.execute(
            select(ChatMessage.created_at)
            .where(ChatMessage.user_id == user_id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.desc())
            .limit(200)
        )
        timestamps = [m[0] for m in messages.all()]

    if len(timestamps) < 10:
        return {"peak_hours": [], "quiet_hours": [], "sample_size": len(timestamps)}

    # Count messages per hour (in user's local timezone)
    hour_counts = Counter()
    for ts in timestamps:
        hour_counts[ts.hour] += 1

    sorted_hours = sorted(hour_counts.keys(), key=lambda h: hour_counts[h], reverse=True)
    peak = sorted_hours[:4]   # top 4 hours
    quiet = [h for h in range(24) if hour_counts.get(h, 0) == 0]

    return {"peak_hours": peak, "quiet_hours": quiet, "sample_size": len(timestamps)}


async def compute_procrastination_index(user_id: str) -> dict:
    """Measure how early/late the user starts working on assignments."""
    # Compare: assignment due_date vs when user first mentions it or creates a task
    # Lower = more procrastination (starts closer to deadline)
    ...


async def compute_engagement_by_category(user_id: str) -> dict:
    """Aggregate ProactiveFeedback into per-category engagement rates."""
    summary = await get_feedback_summary(user_id, days=60)
    return summary.get("engagement_by_category", {})


async def compute_signal_sensitivity(user_id: str) -> dict:
    """Which signal types does this user actually care about?
    Based on: engagement with messages triggered by each signal type."""
    async with async_session() as session:
        feedbacks = await session.execute(
            select(ProactiveFeedback)
            .where(ProactiveFeedback.user_id == user_id)
        )
        all_fb = feedbacks.scalars().all()

    signal_stats: dict[str, dict] = {}
    for fb in all_fb:
        for signal in (fb.trigger_signals or []):
            if signal not in signal_stats:
                signal_stats[signal] = {"total": 0, "engaged": 0}
            signal_stats[signal]["total"] += 1
            if fb.outcome in ("engaged", "button_click"):
                signal_stats[signal]["engaged"] += 1

    sensitivity = {}
    for signal, stats in signal_stats.items():
        rate = stats["engaged"] / stats["total"] if stats["total"] >= 3 else 0.5
        if rate >= 0.6:
            sensitivity[signal] = "high"
        elif rate >= 0.3:
            sensitivity[signal] = "medium"
        else:
            sensitivity[signal] = "low"

    return sensitivity
```

---

### 4.4 Preference Learning

**What it is**: The system that closes the loop — observes outcomes and updates the user model accordingly.

**Two mechanisms:**

#### A. Nightly Reflection Job

Inspired by the ComPeer research ("nightly reflection" step). A scheduled job that runs once per day (at 3 AM user-local time) and:

1. **Recomputes behavioral metrics** — active_hours, procrastination_index, message_length_pref, etc.
2. **Consolidates memory** — merge duplicate entities, decay stale facts (reduce confidence), delete facts with confidence below 0.2
3. **Updates signal sensitivity** — from feedback data
4. **Detects new patterns** — run `patterns.py` (the LLM-based detector) but only weekly, not nightly (expensive)
5. **Updates trust level cache** — so prefilter doesn't need to compute it every cycle

```python
async def nightly_reflection(user_id: str) -> None:
    """Run once per day per user. Consolidates and updates the user model."""

    # 1. Recompute behavioral metrics
    behaviors = {
        "active_hours": await compute_active_hours(user_id),
        "engagement_by_cat": await compute_engagement_by_category(user_id),
        "signal_sensitivity": await compute_signal_sensitivity(user_id),
        "response_speed": await compute_response_speed(user_id),
        "message_length_pref": await compute_message_length_pref(user_id),
    }

    async with async_session() as session:
        for key, value in behaviors.items():
            existing = await session.execute(
                select(UserBehavior).where(
                    UserBehavior.user_id == user_id,
                    UserBehavior.behavior_key == key,
                )
            )
            behavior = existing.scalar_one_or_none()
            if behavior:
                behavior.value = value
                behavior.sample_size = value.get("sample_size", 0)
                behavior.last_computed = datetime.utcnow()
            else:
                session.add(UserBehavior(
                    id=generate_uuid(),
                    user_id=user_id,
                    behavior_key=key,
                    value=value,
                    sample_size=value.get("sample_size", 0),
                ))
        await session.commit()

    # 2. Decay stale memory facts
    await decay_stale_facts(user_id)

    # 3. Consolidate duplicate entities
    await consolidate_entities(user_id)

    # 4. Update user aggregate metrics
    await update_user_metrics(user_id)
```

#### B. Real-time micro-updates

Some preference signals are too valuable to wait for nightly:

- **User dismisses a proactive message** → immediately lower that category's weight
- **User says "stop reminding me about X"** → create a `SignalState` suppression for that signal type
- **User responds enthusiastically to a type of message** → boost that category

These are handled in `feedback.py` and the existing `check_and_update_feedback()` function, but should also propagate to `UserBehavior` via lightweight incremental updates.

---

## 5. Data Model Changes

### New models to create:

```python
class UserEntity(Base):
    __tablename__ = "user_entities"
    # ... (defined above in section 4.2.A)

class UserBehavior(Base):
    __tablename__ = "user_behaviors"
    # ... (defined above in section 4.3)
```

### Modifications to existing models:

**`User` — add academic context + aggregate metrics:**
```python
# New columns on User:
academic_year = Column(Integer, nullable=True)
faculty = Column(String, nullable=True)
major = Column(String, nullable=True)
graduation_year = Column(Integer, nullable=True)
has_canvas = Column(Boolean, default=False)
has_google = Column(Boolean, default=False)
has_microsoft = Column(Boolean, default=False)
nusmods_imported = Column(Boolean, default=False)
total_messages = Column(Integer, default=0)
proactive_engagement_rate = Column(Float, default=0.5)
avg_response_latency_seconds = Column(Float, nullable=True)
last_active_at = Column(DateTime, nullable=True)
```

**`MemoryFact` — standardize categories:**
No schema change needed, but enforce category conventions in code:
```python
VALID_CATEGORIES = {
    "preference:communication", "preference:schedule", "preference:academic",
    "preference:food", "preference:social",
    "context:academic", "context:social", "context:health", "context:work",
    "relationship:friend", "relationship:family", "relationship:professor",
    "pattern:temporal", "pattern:behavioral", "pattern:emotional",
    "entity:person", "entity:place", "entity:task", "entity:event",
    "entity:preference",  # legacy entity extraction category
    "timetable", "exam",  # NUSMods data
}
```

---

## 6. Implementation Plan

### Phase 1: Activate pgvector (Biggest bang for effort)

**Why first**: Semantic search transforms recall quality. ILIKE → pgvector is a qualitative leap. And the infrastructure (pgvector extension, Vector column) is already in place.

1. **Create embedding utility** — `donna/memory/embeddings.py`
   - `async def embed_text(text: str) -> list[float]` using `text-embedding-3-small`
   - Batch embedding function for backfilling

2. **Wire embeddings into memory_writer** — when storing MemoryFact, compute and set embedding
3. **Wire embeddings into entities.py** — when storing entity MemoryFacts, set embedding
4. **Replace ILIKE in recall.py** — use pgvector cosine distance `<=>` operator
5. **Backfill existing facts** — one-time migration script to embed all existing MemoryFact rows

**Files to create/modify:**
- CREATE `donna/memory/embeddings.py`
- MODIFY `agent/nodes/memory.py` — use embed_text when storing facts
- MODIFY `donna/memory/entities.py` — use embed_text when storing entities
- MODIFY `donna/memory/recall.py` — replace ILIKE with pgvector search
- CREATE `scripts/backfill_embeddings.py` — one-time migration

### Phase 2: Structured entities (UserEntity table)

**Why second**: This gives Donna structured knowledge about the user's world — people they know, places they go, courses they take — instead of freeform text.

6. **Create UserEntity model** in `db/models.py`
7. **Modify entities.py** — instead of (or in addition to) storing as MemoryFact, upsert into UserEntity. On re-mention, increment `mention_count` and update `last_mentioned`.
8. **Create entity query functions** — `get_user_entities(user_id, entity_type)`, `get_frequently_mentioned(user_id, limit)`, `get_entity_by_name(user_id, name)`
9. **Wire into context.py** — include top entities in the context window for the LLM

**Files to create/modify:**
- MODIFY `db/models.py` — add UserEntity
- MODIFY `donna/memory/entities.py` — upsert to UserEntity
- CREATE `donna/memory/entity_store.py` — query functions
- MODIFY `donna/brain/context.py` — include entities in context
- MODIFY `agent/nodes/context.py` — include entities in reactive context

### Phase 3: Behavioral model (UserBehavior table + nightly reflection)

10. **Create UserBehavior model** in `db/models.py`
11. **Create behavioral computation functions** — `donna/brain/behaviors.py`
    - `compute_active_hours()`, `compute_engagement_by_category()`, `compute_signal_sensitivity()`, `compute_response_speed()`, `compute_message_length_pref()`
12. **Create nightly reflection job** — `donna/reflection.py`
    - Orchestrates all computations + memory decay + entity consolidation
13. **Schedule nightly reflection** — add to `agent/scheduler.py` (3 AM user-local)
14. **Wire into prefilter** — use `signal_sensitivity` to boost/suppress signals before LLM
15. **Wire into candidates prompt** — include behavioral summary so LLM adapts

**Files to create/modify:**
- MODIFY `db/models.py` — add UserBehavior
- CREATE `donna/brain/behaviors.py` — computation functions
- CREATE `donna/reflection.py` — nightly job
- MODIFY `agent/scheduler.py` — schedule reflection
- MODIFY `donna/brain/prefilter.py` — use signal_sensitivity
- MODIFY `donna/brain/candidates.py` — include behaviors in prompt

### Phase 4: Enhanced static profile

16. **Add academic columns to User** model
17. **Add onboarding step** — after current flow, conversationally ask year + major
18. **Add integration status flags** — update `has_canvas`, `has_google`, etc. when user connects
19. **Create `get_user_snapshot()`** — single function that assembles the full user model for any layer

**Files to create/modify:**
- MODIFY `db/models.py` — new User columns
- MODIFY `agent/nodes/onboarding.py` — add academic context step
- MODIFY `api/auth.py` — set integration flags on connect
- CREATE `donna/user_model.py` — `get_user_snapshot()` function

### Phase 5: Memory maintenance

20. **Implement fact decay** — reduce confidence by 0.05 per week for unreferenced facts
21. **Implement entity consolidation** — merge near-duplicate UserEntity rows (fuzzy name match)
22. **Implement memory pruning** — delete MemoryFact rows with confidence < 0.2 and age > 30 days
23. **Implement pattern re-detection** — weekly LLM-based pattern detection (existing `patterns.py`), but scheduled, not manual

**Files to create/modify:**
- MODIFY `donna/reflection.py` — add decay, consolidation, pruning
- MODIFY `agent/scheduler.py` — schedule weekly pattern detection

### Phase 6: Wire everything into the `get_user_snapshot()`

24. **Create the unified snapshot function:**

```python
async def get_user_snapshot(user_id: str) -> dict:
    """Assemble the complete user model for any layer to consume.

    Returns a dict with four sections: profile, memory, behaviors, preferences.
    This is THE canonical way to understand a user.
    """
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return {}

        # Static profile
        profile = {
            "name": user.name,
            "timezone": user.timezone,
            "academic_year": user.academic_year,
            "faculty": user.faculty,
            "major": user.major,
            "wake_time": user.wake_time,
            "sleep_time": user.sleep_time,
            "tone_preference": user.tone_preference,
            "integrations": {
                "canvas": user.has_canvas,
                "google": user.has_google,
                "microsoft": user.has_microsoft,
                "nusmods": user.nusmods_imported,
            },
            "days_active": (datetime.utcnow() - user.created_at).days if user.created_at else 0,
            "total_messages": user.total_messages or 0,
            "engagement_rate": user.proactive_engagement_rate or 0.5,
        }

        # Key entities (top 20 by mention count)
        entities_result = await session.execute(
            select(UserEntity)
            .where(UserEntity.user_id == user_id)
            .order_by(UserEntity.mention_count.desc())
            .limit(20)
        )
        entities = [
            {
                "type": e.entity_type,
                "name": e.name,
                "sentiment": e.sentiment,
                "mentions": e.mention_count,
                "metadata": e.metadata,
            }
            for e in entities_result.scalars().all()
        ]

        # Behavioral model
        behaviors_result = await session.execute(
            select(UserBehavior)
            .where(UserBehavior.user_id == user_id)
        )
        behaviors = {
            b.behavior_key: b.value
            for b in behaviors_result.scalars().all()
        }

        # Recent memory facts (non-entity, non-pattern — pure observations)
        facts_result = await session.execute(
            select(MemoryFact)
            .where(
                MemoryFact.user_id == user_id,
                ~MemoryFact.category.startswith("entity:"),
                MemoryFact.category != "pattern",
            )
            .order_by(MemoryFact.last_referenced.desc().nullslast(),
                       MemoryFact.created_at.desc())
            .limit(15)
        )
        facts = [
            {"fact": f.fact, "category": f.category, "confidence": f.confidence}
            for f in facts_result.scalars().all()
        ]

    return {
        "profile": profile,
        "entities": entities,
        "behaviors": behaviors,
        "memory_facts": facts,
    }
```

25. **Replace ad-hoc queries in context.py and agent/nodes/context.py** with `get_user_snapshot()` calls.

---

## 7. How Other Layers Consume the User Model

### Layer 1 (Signal Collection)

- **`signal_sensitivity`** from UserBehavior → If user has `"email_unread": "low"`, the email signal collector can skip or lower urgency for `EMAIL_UNREAD_PILING`
- **`active_hours`** → time-based signals (morning/evening window) use actual user behavior, not just declared wake/sleep times
- **Academic context** → Canvas signals can differentiate between core modules and electives for urgency scoring

### Layer 2 (Decision Engine)

- **Trust level** (already wired) → score threshold, daily cap, min urgency
- **`engagement_by_cat`** → candidates.py prompt includes engagement rates so LLM biases toward categories the user responds to
- **`signal_sensitivity`** → prefilter suppresses signals the user doesn't care about
- **Behavioral patterns** → candidates.py prompt includes patterns so messages feel personally relevant
- **Entities** → candidates can reference people/places the user knows ("Noor mentioned wanting to grab lunch")

### Layer 4 (Message Generation)

- **`tone_preference`** + `message_length_pref` → composer adapts style (currently `tone_preference` is collected but never used in the composer prompt)
- **Entity context** → composer knows who "Noor" is when the user mentions them
- **Academic context** → composer understands course codes and academic terminology appropriate to the user's level

### Layer 5 (Delivery)

- **`active_hours`** → optimal send time (don't just avoid quiet hours — actively prefer peak hours)
- **`response_speed`** → if user typically responds in 3 minutes, a 30-minute silence after a proactive message = likely ignored

### Layer 6 (Feedback Processing)

- **All of UserBehavior** → feedback updates the behavioral model
- **Entity mentions in replies** → update entity sentiment and mention_count
- **Proactive engagement rate** → rolled up into User.proactive_engagement_rate nightly

---

## Appendix: LLM Cost Analysis for Layer 3

| Operation | Model | Frequency | Cost/call | Daily cost (100 users) |
|---|---|---|---|---|
| Entity extraction | GPT-4o | Every user message | ~$0.003 | ~$6 (at 20 msg/user/day) |
| Memory fact extraction | GPT-4o | Every user message | ~$0.003 | ~$6 |
| Embeddings | text-embedding-3-small | Every new fact | ~$0.000001 | ~$0.004 |
| Memory recall (pgvector) | text-embedding-3-small (query) | Every Donna cycle | ~$0.000001 | ~$0.03 |
| Pattern detection (LLM) | GPT-4o | Weekly per user | ~$0.02 | ~$0.28/week |
| Behavioral computation | None (deterministic) | Nightly per user | $0 | $0 |

**Biggest cost driver**: Entity + memory extraction on every message ($12/day for 100 active users). Optimization: use GPT-4o-mini for entity extraction (quality is sufficient for extraction tasks, 10x cheaper).

**Biggest value unlock**: pgvector semantic search ($0.004/day) replaces LLM-based recall query generation ($2-5/day). Cheaper AND better.
