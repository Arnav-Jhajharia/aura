# Layer 1: Signal Collection — Architecture & Implementation Guide

> **Purpose**: This document is the definitive reference for Donna's Signal Collection layer — every integration source, the full ingestion-to-output pipeline, every known bug, and the concrete changes needed to make it production-perfect.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Integration Sources](#2-integration-sources)
   - 2.1 Google Calendar
   - 2.2 Canvas LMS
   - 2.3 Gmail
   - 2.4 Internal DB (Time, Mood, Tasks, Habits, Memory)
   - 2.5 NUSMods (Planned)
   - 2.6 WhatsApp Metadata
3. [Signal Taxonomy](#3-signal-taxonomy)
4. [The L1 Pipeline](#4-the-l1-pipeline)
   - 4.1 Sources
   - 4.2 Ingestion
   - 4.3 Normalization
   - 4.4 Deduplication
   - 4.5 Enrichment & Cross-Referencing
   - 4.6 Signal Output
5. [Current Implementation Audit](#5-current-implementation-audit)
6. [Critical Bugs](#6-critical-bugs)
7. [Target Architecture](#7-target-architecture)
8. [Implementation Plan](#8-implementation-plan)

---

## 1. Overview

Layer 1 is the sensory nervous system of Donna. Every 5 minutes, the APScheduler fires `donna_loop()` for each onboarded user. The very first step is `collect_all_signals()`, which polls 4 external/internal sources concurrently and produces a sorted list of `Signal` objects. These signals are the **only input** to the Brain layer (Layer 2) — if signals are noisy, duplicated, or missing context, every downstream decision suffers.

**Current flow:**
```
APScheduler (5 min)
  → donna_loop(user_id)
    → collect_all_signals(user_id)         # Layer 1
      → collect_calendar_signals()         # Google Calendar via Composio
      → collect_canvas_signals()           # Canvas LMS via direct httpx
      → collect_email_signals()            # Gmail via Composio
      → collect_internal_signals()         # DB queries (mood, tasks, habits, memory)
    → build_context()                      # Layer 2 starts here
    → generate_candidates()
    → score_and_filter()
    → send_proactive_message()
```

**Target flow (what this document designs):**
```
APScheduler (5 min)
  → donna_loop(user_id)
    → collect_all_signals(user_id)
      → [Source Adapters]                  # Fetch raw data from each integration
      → [Normalizer]                       # Convert to unified Signal format + user timezone
      → [Deduplicator]                     # Suppress already-seen signals via signal_state table
      → [Enricher]                         # Cross-reference signals for compound insights
      → [Prioritized Signal List]          # Sorted, capped, ready for Layer 2
```

---

## 2. Integration Sources

### 2.1 Google Calendar

**Authentication**: OAuth2 via Composio SDK. The user connects Google during onboarding via a Composio redirect flow (`api/auth.py`). Composio manages token refresh.

**SDK**: Composio (synchronous Python SDK wrapped with `asyncio.to_thread()`).

**Tool file**: `tools/calendar.py`

**API Actions Used:**

| Composio Slug | Purpose | Current Usage |
|---|---|---|
| `GOOGLECALENDAR_FIND_EVENT` | Fetch events in a time range | Signal collector + reactive queries |
| `GOOGLECALENDAR_CREATE_EVENT` | Create new events | Reactive tool only |
| `GOOGLECALENDAR_FIND_FREE_SLOTS` | Native free-slot detection | Reactive tool (falls back to local algo) |

**Data shape returned by `get_calendar_events()`:**
```python
{
    "title": str,       # event summary
    "start": str,       # ISO datetime (from dateTime or date field)
    "end": str,         # ISO datetime
    "location": str,    # physical/virtual location
}
```

**Signal collector**: `donna/signals/calendar.py`

**Signals emitted:**

| Signal | Trigger | Data |
|---|---|---|
| `CALENDAR_EMPTY_DAY` | 0 events today | `{date}` |
| `CALENDAR_BUSY_DAY` | >= 5 events today | `{event_count, date}` |
| `CALENDAR_EVENT_APPROACHING` | Event starts within 60 minutes | `{title, start, minutes_away, location}` |
| `CALENDAR_EVENT_STARTED` | Event started within last 15 minutes | `{title, start, minutes_ago}` |
| `CALENDAR_GAP_DETECTED` | >= 2h free gap in remaining day | `{start, end, duration_hours}` |

**Rate limits**: Google Calendar API allows 1,000,000 queries/day per project. At 5-min intervals with ~100 users, that's ~28,800 calls/day — well within limits. Per-user rate limit is 500 requests per 100 seconds.

**Known issues:**
- All time comparisons use UTC. A student in Singapore (UTC+8) who has a 9 AM class will see `CALENDAR_EVENT_APPROACHING` calculated against UTC, potentially off by 8 hours.
- `day_end` is hardcoded to 22:00 UTC in the gap detection algorithm, which is 6 AM SGT — meaningless.
- `get_calendar_events()` uses `datetime.utcnow()` (deprecated) instead of `datetime.now(timezone.utc)`.
- No all-day event handling — these events use `date` instead of `dateTime` and may parse incorrectly.

---

### 2.2 Canvas LMS

**Authentication**: Personal Access Token (PAT) stored in the `OAuthToken` table with `provider="canvas"`. User pastes their Canvas PAT during onboarding via `api/onboard.py`. Composio does **not** support Canvas, so this is a direct httpx integration.

**Tool file**: `tools/canvas.py`

**API Endpoints Used:**

| Endpoint | Purpose | Pagination |
|---|---|---|
| `GET /api/v1/users/self/upcoming_events` | Get upcoming assignments + calendar events | Link header (handled by `_fetch_all_pages`) |
| `GET /api/v1/courses` | List active courses | Link header |
| `GET /api/v1/courses/{id}/students/submissions` | Get graded submissions | Link header |

**Data shape returned by `get_canvas_assignments()`:**
```python
{
    "title": str,           # assignment name
    "course": str,          # context_name (course name)
    "due_date": str | None, # ISO datetime or None
    "points": float | None, # points_possible
    "submitted": bool,      # has_submitted_submissions
}
```

**Data shape returned by `get_canvas_grades()`:**
```python
{
    "assignment": str,       # assignment name
    "course": str,           # course name
    "score": float,          # student's score
    "points_possible": float # max score
}
```

**Signal collector**: `donna/signals/canvas.py`

**Signals emitted:**

| Signal | Trigger | Data |
|---|---|---|
| `CANVAS_OVERDUE` | Past due + not submitted | `{title, course, due_date, hours_overdue, points}` |
| `CANVAS_DEADLINE_APPROACHING` | Within threshold + not submitted | `{title, course, due_date, hours_until, urgency_label, points}` |
| `CANVAS_GRADE_POSTED` | **NEVER — not implemented** | — |

**Deadline thresholds (tightest wins):**
```
3 hours   → "3_hours"
12 hours  → "12_hours"
24 hours  → "1_day"
48 hours  → "2_days"
72 hours  → "3_days"
```

**Rate limits**: Canvas API rate limit is 700 requests per 10 minutes per user token. The `upcoming_events` endpoint is lightweight (single paginated call). The `get_canvas_grades()` function makes N+1 calls (1 for courses + 1 per course for submissions), which could be expensive for students with many active courses.

**Known issues:**
- `CANVAS_GRADE_POSTED` is defined in `SignalType` but never implemented in the collector. The `get_canvas_grades()` function exists in `tools/canvas.py` but is never called from `donna/signals/canvas.py`.
- No caching — fetches all assignments every 5 minutes even if nothing changed.
- The `upcoming_events` endpoint only returns future events, so `CANVAS_OVERDUE` will only catch assignments that were fetched before their due date (race condition if the service was down).
- No handling of Canvas quiz events or discussion deadlines (only assignments).

---

### 2.3 Gmail

**Authentication**: OAuth2 via Composio SDK, chained with Google Calendar (Gmail first, then Calendar). Composio handles token refresh.

**SDK**: Composio (synchronous, wrapped with `asyncio.to_thread()`).

**Tool file**: `tools/email.py`

**API Actions Used:**

| Composio Slug | Purpose | Current Usage |
|---|---|---|
| `GMAIL_FETCH_EMAILS` | Fetch emails with query filter | Signal collector + reactive queries |
| `GMAIL_SEND_EMAIL` | Send email | Reactive tool only |

**Query filters:**
```python
"unread"    → "is:unread"
"important" → "is:important is:unread"
"all"       → ""
```

**Data shape returned by `get_emails()`:**
```python
{
    "id": str,       # Gmail message ID
    "from": str,     # sender
    "subject": str,  # subject line
    "date": str,     # date string
    "snippet": str,  # preview text
}
```

**Signal collector**: `donna/signals/email.py`

**Signals emitted:**

| Signal | Trigger | Data |
|---|---|---|
| `EMAIL_UNREAD_PILING` | >= 5 unread emails | `{unread_count, subjects[0:5]}` |
| `EMAIL_IMPORTANT_RECEIVED` | Each important unread email (up to 5) | `{from, subject, date, snippet}` |

**Rate limits**: Gmail API allows 250 quota units per user per second. `GMAIL_FETCH_EMAILS` uses ~5 units per call. At 2 calls per 5-min cycle (unread + important), we're well within limits.

**Known issues:**
- **No deduplication on important emails**: The same important email fires `EMAIL_IMPORTANT_RECEIVED` every 5-minute cycle until the user reads it. Over 1 hour, that's 12 duplicate signals per email.
- **No email ID tracking**: We don't store which email IDs we've already signaled about.
- "Important" is Gmail's internal classification — may not match what the student considers important.
- No NUS-specific email filtering (e.g., professor emails, admin notices, official NUS comms).
- The `count` parameter limits returned emails but doesn't prevent API pagination internally.

---

### 2.4 Internal DB (Time, Mood, Tasks, Habits, Memory)

**Authentication**: Direct SQLAlchemy async sessions — no external auth needed.

**Signal collector**: `donna/signals/internal.py`

**Data sources queried:**

| DB Model | What's queried | Purpose |
|---|---|---|
| `User` | `wake_time`, `sleep_time`, `name` | Determine morning/evening windows |
| `ChatMessage` | Latest user message timestamp | Calculate interaction gap |
| `MoodLog` | Last 7 days of mood scores | Detect mood trends |
| `Task` | Pending tasks with due dates | Find overdue + due-today |
| `Habit` | All habits with last_logged, streak | Detect streak risk / milestones |
| `MemoryFact` | Recent entity:place / entity:event facts | Memory relevance windows |

**Signals emitted:**

| Signal | Trigger | Data |
|---|---|---|
| `TIME_MORNING_WINDOW` | Within +/-1h of wake_time | `{wake_time, user_name}` |
| `TIME_EVENING_WINDOW` | Within +/-1h of sleep_time | `{sleep_time, user_name}` |
| `TIME_SINCE_LAST_INTERACTION` | >= 6h since last user message | `{hours_since}` |
| `MOOD_TREND_DOWN` | Last 3 moods avg <= 4 AND < overall avg - 1 | `{recent_avg, overall_avg, last_score, days_tracked}` |
| `MOOD_TREND_UP` | Last 3 moods avg >= 7 AND > overall avg + 1 | `{recent_avg, overall_avg, last_score}` |
| `TASK_OVERDUE` | Pending task with due_date < now | `{title, due_date, hours_overdue, priority, source}` |
| `TASK_DUE_TODAY` | Pending task due between now and end of day | `{title, due_date, priority, source}` |
| `HABIT_STREAK_AT_RISK` | Daily habit: >= 20h since logged; Weekly: >= 144h | `{habit_name, current_streak, hours_since_logged}` |
| `HABIT_STREAK_MILESTONE` | Streak is a multiple of 7 | `{habit_name, current_streak}` |
| `MEMORY_RELEVANCE_WINDOW` | Evening/weekend + stored place/event memories | `{reason, facts[0:3], is_evening, is_weekend}` |

**Known issues:**
- **Critical timezone bug**: Line 17 does `now = datetime.now(timezone.utc).replace(tzinfo=None)` — strips timezone, then uses `now.hour` as if it's local time. Line 29 has a comment acknowledging this: `# NOTE: should be user's local time; using UTC for now`. For SGT users, morning/evening windows are 8 hours off.
- **`TASK_OVERDUE` re-fires every cycle**: No dedup. A task overdue by 3 days will emit `TASK_OVERDUE` every 5 minutes (288 duplicate signals/day).
- **`HABIT_STREAK_MILESTONE` re-fires every cycle**: If streak is 14 (multiple of 7), this signal fires every 5 minutes forever until the streak changes.
- **`MEMORY_RELEVANCE_WINDOW` is noisy**: Fires every 5 minutes during all evenings and weekends if any place/event facts exist.
- Morning/evening window check uses `abs(current_hour - X) <= 1`, which means it fires for 3 consecutive hours (e.g., wake at 8 → fires at 7, 8, 9).
- Mood trend requires 3+ entries in 7 days — most students won't log mood that frequently.

---

### 2.5 NUSMods (Planned — Not Yet Implemented)

**What it is**: NUSMods is the de facto timetable planner for NUS students. During onboarding, users can paste their NUSMods share URL, which gets parsed into `MemoryFact` entries via `api/onboard.py`.

**Current state**: URL parsing stores module codes as memory facts, but there is **no signal collector** for NUSMods data. The timetable data is static (doesn't change within a semester).

**Potential signals:**
- `NUSMODS_CLASS_APPROACHING` — class starting within 30 minutes
- `NUSMODS_EXAM_APPROACHING` — exam within 48 hours
- `NUSMODS_FREE_BLOCK` — gap between classes (for study suggestions)

**Integration approach**: Since NUSMods data is static per semester, it should be stored in a structured format (not just memory facts) and cross-referenced with Google Calendar. If the student has both NUSMods classes and Google Calendar events, we can detect conflicts and true free time.

---

### 2.6 WhatsApp Metadata (Implicit Signals)

**What it is**: The user's WhatsApp interaction patterns are already partially captured (last message timestamp in `ChatMessage`), but we're not extracting all available metadata.

**Potential additional signals from WhatsApp webhook data:**
- Message frequency patterns (bursts vs. silence)
- Time-of-day usage patterns (when does this user typically message?)
- Response latency (how quickly does the user reply to Donna?)
- Message length trends (short replies = busy/disengaged, long replies = engaged)

**Current state**: Only `TIME_SINCE_LAST_INTERACTION` is derived from WhatsApp metadata. The richer behavioral signals are not collected.

---

## 3. Signal Taxonomy

All 21 signal types are defined in `donna/signals/base.py`. Each has a built-in `urgency_hint` (1-10):

**High urgency (8):**
- `CALENDAR_EVENT_APPROACHING` — event starting within 60 min
- `CANVAS_OVERDUE` — assignment past due, not submitted
- `CANVAS_DEADLINE_APPROACHING` — assignment due within threshold
- `EMAIL_IMPORTANT_RECEIVED` — important unread email

**Medium urgency (5):**
- `CALENDAR_GAP_DETECTED` — 2+ hour free block
- `TASK_OVERDUE` — internal task past due
- `TASK_DUE_TODAY` — internal task due today
- `MOOD_TREND_DOWN` — mood declining
- `EMAIL_UNREAD_PILING` — 5+ unread emails
- `HABIT_STREAK_AT_RISK` — habit not logged in time
- `MEMORY_RELEVANCE_WINDOW` — relevant memories + time context

**Low urgency (3) — everything else:**
- `CALENDAR_EMPTY_DAY`, `CALENDAR_BUSY_DAY`, `CALENDAR_EVENT_STARTED`
- `TIME_MORNING_WINDOW`, `TIME_EVENING_WINDOW`, `TIME_SINCE_LAST_INTERACTION`
- `MOOD_TREND_UP`, `HABIT_STREAK_MILESTONE`, `CANVAS_GRADE_POSTED`

**Design note on urgency_hint**: This is a static property based solely on signal type. It doesn't account for context (e.g., a 3-hour deadline for a 40-point assignment should be more urgent than a 3-hour deadline for a 5-point assignment). The Brain layer (Layer 2) can override this via the LLM scoring, but having a smarter default would reduce LLM load.

---

## 4. The L1 Pipeline

The pipeline transforms raw external data into clean, deduplicated, enriched signals ready for Layer 2.

### 4.1 Sources (Raw Data Fetch)

Each source adapter is responsible for:
1. Checking if the integration is connected (fail gracefully if not)
2. Making the API call with appropriate parameters
3. Returning raw data in its native shape
4. Handling API errors, rate limits, and timeouts

**Current implementation**: The source adapters are the tool functions in `tools/`. They already handle connection checks and error returns. The signal collectors in `donna/signals/` call these tools and transform the results.

**What needs to change**: Nothing structurally — the source adapters work. But we should add:
- **Response caching**: For sources that don't change frequently (Canvas assignments, NUSMods), cache responses and only re-fetch when stale.
- **Connection health tracking**: If a source fails 3+ times consecutively, stop polling it and alert the user once.
- **Rate limit awareness**: Track API call counts and back off before hitting limits.

### 4.2 Ingestion (Raw → Signal Conversion)

This is what the current signal collectors do: take raw data from sources and emit `Signal` objects with structured `data` dicts.

**Current implementation**: Each collector (`calendar.py`, `canvas.py`, `email.py`, `internal.py`) runs independently. They're gathered concurrently in `collector.py`.

**What needs to change**:
- **Timezone conversion should happen here**, not later. Every signal's `data` dict should include both UTC and local times.
- **User timezone must be passed to every collector** — currently only `internal.py` accesses the User model, and even it uses UTC.

### 4.3 Normalization

Normalization ensures all signals have a consistent shape regardless of source. Currently, this layer doesn't exist — each collector produces signals with different `data` dict shapes.

**Target normalization rules:**

1. **All timestamps in `data` must be in user's local timezone** with UTC stored as a secondary field.
2. **All signals must carry a `source` field** identifying the integration.
3. **All signals must carry a `dedup_key`** — a deterministic hash that uniquely identifies this signal instance so we can suppress duplicates.
4. **Urgency should be computed, not just typed** — factor in points, time remaining, historical user behavior.

**Proposed `Signal` dataclass extension:**
```python
@dataclass
class Signal:
    type: SignalType
    user_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""            # NEW: "google_calendar", "canvas", "gmail", "internal"
    dedup_key: str = ""         # NEW: deterministic hash for dedup
    urgency: float = 0.0       # NEW: computed urgency (replaces urgency_hint property)
    local_timestamp: str = ""   # NEW: user-local time string for display

    def compute_dedup_key(self) -> str:
        """Generate a deterministic key for this signal instance."""
        # Examples:
        # calendar_event_approaching:event_title:2025-02-17T09:00
        # canvas_overdue:assignment_title:CS2103
        # email_important:message_id
        parts = [self.type.value]
        if "title" in self.data:
            parts.append(self.data["title"])
        if "due_date" in self.data:
            parts.append(self.data["due_date"])
        if "id" in self.data:
            parts.append(self.data["id"])
        return ":".join(parts)
```

### 4.4 Deduplication

This is the **biggest missing piece** in the current implementation. Without dedup, the same signal fires every 5 minutes, flooding Layer 2 with noise.

**The problem**: Every 5-minute cycle is stateless. The collectors don't know what they emitted 5 minutes ago. So:
- An overdue Canvas assignment emits `CANVAS_OVERDUE` 288 times per day
- An important email emits `EMAIL_IMPORTANT_RECEIVED` until the user reads it (12x/hour)
- `HABIT_STREAK_MILESTONE` fires every cycle while the streak stays on a multiple of 7
- `TASK_OVERDUE` fires every cycle for every overdue task
- `MEMORY_RELEVANCE_WINDOW` fires every cycle during evenings and weekends

**Solution: Signal State Table**

Create a `signal_state` table to track what signals have been emitted and when:

```python
class SignalState(Base):
    __tablename__ = "signal_state"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    dedup_key = Column(String, nullable=False)
    signal_type = Column(String, nullable=False)
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    times_seen = Column(Integer, default=1)
    last_acted_on = Column(DateTime, nullable=True)  # when Brain last sent a message about this
    suppressed_until = Column(DateTime, nullable=True)  # manual suppression

    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_user_signal"),
    )
```

**Dedup rules by signal type:**

| Signal Type | Dedup Strategy |
|---|---|
| `CALENDAR_EVENT_APPROACHING` | Emit once per event when entering 60-min window. Re-emit at 15-min mark if no action taken. |
| `CALENDAR_EVENT_STARTED` | Emit once per event. |
| `CALENDAR_GAP_DETECTED` | Emit once per gap per day. |
| `CALENDAR_BUSY_DAY` / `CALENDAR_EMPTY_DAY` | Emit once per day (morning window only). |
| `CANVAS_OVERDUE` | Emit once. Re-emit every 24h if still unresolved. |
| `CANVAS_DEADLINE_APPROACHING` | Emit once per threshold tier (so max 5 emissions as deadline approaches). |
| `CANVAS_GRADE_POSTED` | Emit once per grade. |
| `EMAIL_IMPORTANT_RECEIVED` | Emit once per email ID. Never re-emit. |
| `EMAIL_UNREAD_PILING` | Emit once when crossing threshold. Re-emit if count increases by 5+. |
| `TASK_OVERDUE` | Emit once. Re-emit every 24h. |
| `TASK_DUE_TODAY` | Emit once per task per day. |
| `HABIT_STREAK_AT_RISK` | Emit once per habit per day. |
| `HABIT_STREAK_MILESTONE` | Emit once per milestone value (7, 14, 21...). |
| `MOOD_TREND_DOWN` / `MOOD_TREND_UP` | Emit once per trend shift. |
| `TIME_MORNING_WINDOW` / `TIME_EVENING_WINDOW` | Emit once per day. |
| `TIME_SINCE_LAST_INTERACTION` | Emit once when crossing 6h. Re-emit at 12h, 24h. |
| `MEMORY_RELEVANCE_WINDOW` | Emit once per evening/weekend block. |

**Dedup function:**
```python
async def deduplicate_signals(
    user_id: str, signals: list[Signal]
) -> list[Signal]:
    """Filter out signals that have already been emitted recently."""
    if not signals:
        return []

    async with async_session() as session:
        # Fetch existing signal states for this user
        existing = await session.execute(
            select(SignalState).where(SignalState.user_id == user_id)
        )
        state_map = {s.dedup_key: s for s in existing.scalars().all()}

        fresh_signals = []
        for signal in signals:
            key = signal.compute_dedup_key()
            state = state_map.get(key)

            if state is None:
                # New signal — always emit
                fresh_signals.append(signal)
                session.add(SignalState(
                    user_id=user_id,
                    dedup_key=key,
                    signal_type=signal.type.value,
                    first_seen=signal.timestamp,
                    last_seen=signal.timestamp,
                ))
            else:
                # Existing signal — check re-emit rules
                state.last_seen = signal.timestamp
                state.times_seen += 1

                if _should_reemit(signal, state):
                    fresh_signals.append(signal)

        await session.commit()

    return fresh_signals
```

### 4.5 Enrichment & Cross-Referencing

Enrichment adds context that no single source can provide on its own. This is where Donna gets smart.

**Cross-reference patterns:**

1. **Calendar + Canvas**: Assignment due tomorrow + no calendar blocks today = "You have free time today to work on [assignment]"
2. **Calendar + Mood**: Busy day (5+ events) + mood trending down = escalate urgency, suggest lighter approach
3. **Canvas + Grades**: Assignment approaching + low grade in that course = higher urgency nudge
4. **Email + Calendar**: Email from professor + class approaching = "Check Professor X's email before class"
5. **Habit + Time**: Habit streak at risk + evening window = "Don't forget to [habit] before bed"
6. **Task + Calendar**: Task due today + 2h calendar gap = "You have a gap from 2-4 PM — perfect for [task]"
7. **Memory + Time**: Weekend + stored restaurant memory + no plans = "Remember that place you wanted to try?"

**Proposed enrichment function:**
```python
async def enrich_signals(
    signals: list[Signal], user_id: str
) -> list[Signal]:
    """Cross-reference signals and add compound insights."""
    enriched = list(signals)  # start with original signals

    # Index signals by type for fast lookup
    by_type: dict[SignalType, list[Signal]] = {}
    for s in signals:
        by_type.setdefault(s.type, []).append(s)

    # Pattern: Calendar gap + Canvas deadline = study suggestion
    gaps = by_type.get(SignalType.CALENDAR_GAP_DETECTED, [])
    deadlines = by_type.get(SignalType.CANVAS_DEADLINE_APPROACHING, [])
    if gaps and deadlines:
        for gap in gaps:
            for deadline in deadlines:
                # Annotate the gap signal with the assignment it could be used for
                gap.data["suggested_task"] = deadline.data.get("title", "")
                gap.data["suggested_course"] = deadline.data.get("course", "")

    # Pattern: Important email + approaching calendar event from same source
    important_emails = by_type.get(SignalType.EMAIL_IMPORTANT_RECEIVED, [])
    approaching_events = by_type.get(SignalType.CALENDAR_EVENT_APPROACHING, [])
    # ... cross-reference by sender/event title matching

    # Pattern: Mood down + busy day = care signal
    mood_down = by_type.get(SignalType.MOOD_TREND_DOWN, [])
    busy_day = by_type.get(SignalType.CALENDAR_BUSY_DAY, [])
    if mood_down and busy_day:
        for signal in mood_down:
            signal.data["compounded_with"] = "busy_day"
            signal.data["care_escalation"] = True

    return enriched
```

### 4.6 Signal Output

The final sorted, capped list of signals passed to Layer 2.

**Current implementation**: `collector.py` sorts by `urgency_hint` descending. No cap.

**Target:**
- Sort by computed `urgency` (not just type-based hint)
- Cap at 10 signals per cycle (prevent prompt bloat in Layer 2)
- Include signal metadata (dedup_key, times_seen, source) for Layer 2 context
- Log signal summary for observability

---

## 5. Current Implementation Audit

### What works well:
- Concurrent collection via `asyncio.gather` with per-collector error isolation
- Graceful degradation when integrations aren't connected (returns empty list)
- Canvas deadline thresholds (5 tiers, tightest wins) — well-designed
- Composio SDK wrapping with `asyncio.to_thread()` — prevents blocking
- Canvas pagination handling via `_fetch_all_pages()` with Link header parsing
- Rules engine has good bones: quiet hours, cooldown, daily cap, dedup by word overlap

### What's broken or missing:

| Area | Status | Impact |
|---|---|---|
| Timezone handling | Broken everywhere | Signals fire at wrong times for non-UTC users |
| Signal dedup | Not implemented | Same signals flood Layer 2 every 5 min |
| `CANVAS_GRADE_POSTED` | Defined but never implemented | Missing a key student-care signal |
| Email dedup | Not implemented | Important emails re-fire indefinitely |
| NUSMods integration | Not implemented | Missing timetable-aware scheduling |
| Cross-signal enrichment | Not implemented | No compound insights |
| Signal caching | Not implemented | Redundant API calls every 5 min |
| Connection health tracking | Not implemented | Silently fails forever |
| Computed urgency | Not implemented | Static urgency by type only |
| All-day calendar events | Not handled | May cause parsing errors |
| `count_proactive_today()` | Counts ALL assistant messages, not just proactive | Daily cap is inaccurate |

---

## 6. Critical Bugs

### Bug 1: Universal Timezone Bug (CRITICAL)

**Affected files**: `donna/signals/calendar.py`, `donna/signals/internal.py`, `tools/calendar.py`

**Root cause**: All time comparisons use UTC. User's local time is never calculated in signal collectors.

**Impact**: For a student in Singapore (UTC+8):
- Morning window (wake_time 07:00) triggers at 07:00 UTC = 15:00 SGT (afternoon)
- Calendar event at 09:00 SGT would be compared against UTC times incorrectly
- Gap detection ends at 22:00 UTC = 06:00 SGT (next morning)

**Fix**: Pass user timezone to all collectors. Convert `now` to user-local before any time comparisons.

```python
import zoneinfo

def _get_user_now(user_tz: str) -> datetime:
    """Get current time in user's timezone (naive, for DB comparison)."""
    try:
        tz = zoneinfo.ZoneInfo(user_tz)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        tz = zoneinfo.ZoneInfo("Asia/Singapore")  # NUS default
    return datetime.now(tz).replace(tzinfo=None)
```

### Bug 2: Email Important Re-fire (HIGH)

**Affected file**: `donna/signals/email.py`

**Root cause**: No tracking of which email IDs have been signaled about.

**Fix**: Store signaled email IDs in `signal_state` table. Only emit for new email IDs.

### Bug 3: Habit Milestone Infinite Fire (HIGH)

**Affected file**: `donna/signals/internal.py`, lines 183-191

**Root cause**: `habit.current_streak % 7 == 0` is checked every cycle. Since the streak doesn't change between cycles, this fires every 5 minutes while streak is at a milestone.

**Fix**: Track in `signal_state` with dedup_key `habit_milestone:{habit_name}:{streak_value}`.

### Bug 4: `count_proactive_today()` Over-counts (MEDIUM)

**Affected file**: `donna/brain/rules.py`, lines 142-157

**Root cause**: Counts ALL assistant messages today, including reactive responses to user queries. Should only count messages where `ChatMessage` has a `proactive=True` flag (which doesn't exist yet).

**Fix**: Add `is_proactive = Column(Boolean, default=False)` to `ChatMessage` model. Set it in `sender.py`. Filter by it in `count_proactive_today()`.

### Bug 5: Deprecated `datetime.utcnow()` (LOW)

**Affected files**: `tools/calendar.py` lines 15, 17, 24, 110, 158

**Root cause**: `datetime.utcnow()` is deprecated in Python 3.12+ and returns a naive datetime.

**Fix**: Replace all with `datetime.now(timezone.utc)`.

---

## 7. Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    collect_all_signals(user_id)              │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Calendar  │  │  Canvas  │  │   Gmail  │  │ Internal │   │
│  │ Adapter   │  │ Adapter  │  │ Adapter  │  │ Adapter  │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │              │              │              │         │
│       └──────────────┴──────────────┴──────────────┘         │
│                          │                                   │
│                    ┌─────▼─────┐                             │
│                    │ Normalize │  ← user timezone, source    │
│                    │ + dedup   │    tags, dedup keys          │
│                    │   keys    │                             │
│                    └─────┬─────┘                             │
│                          │                                   │
│                    ┌─────▼─────┐                             │
│                    │  Dedup    │  ← signal_state table       │
│                    │  Filter   │    (suppress seen signals)  │
│                    └─────┬─────┘                             │
│                          │                                   │
│                    ┌─────▼─────┐                             │
│                    │  Enrich   │  ← cross-reference signals  │
│                    │           │    (calendar+canvas, etc.)  │
│                    └─────┬─────┘                             │
│                          │                                   │
│                    ┌─────▼─────┐                             │
│                    │  Sort &   │  ← computed urgency,        │
│                    │  Cap(10)  │    not just type-hint       │
│                    └─────┬─────┘                             │
│                          │                                   │
│                  [Signal List → Layer 2]                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Implementation Plan

### Phase 1: Fix Critical Bugs (Do First)

1. **Timezone fix across all collectors**
   - Add `user_tz` parameter to all `collect_*_signals()` functions
   - Update `collect_all_signals()` to fetch user timezone and pass it
   - Convert all `now` references to user-local time
   - Fix `tools/calendar.py` to use `datetime.now(timezone.utc)` instead of `datetime.utcnow()`

2. **Add `is_proactive` to ChatMessage**
   - Add column to model
   - Set in `donna/brain/sender.py`
   - Filter in `count_proactive_today()`

### Phase 2: Deduplication

3. **Create `SignalState` model**
   - Add to `db/models.py`
   - Define dedup_key generation per signal type

4. **Implement dedup function**
   - Add `donna/signals/dedup.py`
   - Wire into `collect_all_signals()` after collection, before return
   - Implement per-type re-emit rules

5. **Add dedup_key to Signal dataclass**
   - Extend `Signal` with `source`, `dedup_key`, `local_timestamp`
   - Each collector generates appropriate dedup keys

### Phase 3: Missing Signals

6. **Implement `CANVAS_GRADE_POSTED`**
   - Call `get_canvas_grades()` in canvas signal collector
   - Track last known grades in signal_state
   - Emit when new grade appears

7. **Implement NUSMods signal collector** (if timetable data is stored)
   - Parse stored NUSMods data from MemoryFact
   - Emit class-approaching signals
   - Cross-reference with calendar for conflict detection

### Phase 4: Enrichment

8. **Implement cross-signal enrichment**
   - Add `donna/signals/enrichment.py`
   - Calendar gaps + Canvas deadlines → study suggestions
   - Mood trends + busy day → care escalation
   - Wire into pipeline after dedup

### Phase 5: Optimization

9. **Add response caching**
   - Cache Canvas assignments (TTL: 30 min)
   - Cache calendar events (TTL: 5 min, invalidate on create_event)
   - Use simple in-memory dict with expiry (no Redis needed yet)

10. **Computed urgency**
    - Factor in assignment points, time remaining, grade history
    - Factor in user's historical response patterns
    - Replace static `urgency_hint` property

### Phase 6: Observability

11. **Signal pipeline logging**
    - Log per-cycle: signals collected, signals after dedup, signals after enrichment
    - Track per-source latency and failure rates
    - Alert on repeated source failures

---

## Appendix A: Composio SDK Reference

Composio wraps Google APIs with a synchronous Python SDK. All calls must use `asyncio.to_thread()`.

**Key patterns:**
```python
# Execute a tool action
result = await asyncio.to_thread(
    composio.tools.execute,
    slug="GMAIL_FETCH_EMAILS",
    user_id=user_id,           # Composio entity ID (= our user.id)
    arguments={...},
    dangerously_skip_version_check=True,
)

# Result structure
{
    "successful": bool,
    "data": dict,              # varies by action
    "error": str | None,
}
```

**Gmail slugs**: `GMAIL_FETCH_EMAILS`, `GMAIL_SEND_EMAIL`
**Calendar slugs**: `GOOGLECALENDAR_FIND_EVENT`, `GOOGLECALENDAR_CREATE_EVENT`, `GOOGLECALENDAR_FIND_FREE_SLOTS`

**Connection check:**
```python
connections = await asyncio.to_thread(
    composio.connected_accounts.list,
    user_ids=[user_id],
    statuses=["ACTIVE"],
)
```

## Appendix B: Canvas API Reference

Canvas uses a REST API with Bearer token (PAT) auth.

**Base URL**: Configured via `settings.canvas_base_url` (e.g., `https://canvas.nus.edu.sg`)

**Pagination**: Canvas uses Link headers with `rel="next"` for pagination. Our `_fetch_all_pages()` utility handles this.

**Key endpoints:**
```
GET /api/v1/users/self/upcoming_events      → assignments + calendar events
GET /api/v1/courses                          → list active courses
GET /api/v1/courses/{id}/students/submissions → graded submissions
```

**Rate limit**: 700 requests per 10 minutes per token. The `X-Rate-Limit-Remaining` header tracks remaining quota.

## Appendix C: Signal Flow Example

**Scenario**: Tuesday 2 PM SGT. Student has a CS2103 assignment due Wednesday 11:59 PM, a 2-hour gap from 3-5 PM, mood trending down, and 7 unread emails.

**Raw signals collected:**
1. `CANVAS_DEADLINE_APPROACHING` — CS2103, 34h remaining, urgency_label="2_days"
2. `CALENDAR_GAP_DETECTED` — 3 PM to 5 PM, 2.0 hours
3. `MOOD_TREND_DOWN` — recent_avg=3.7, overall_avg=6.2
4. `EMAIL_UNREAD_PILING` — 7 unread, top 5 subjects

**After normalization:**
- All timestamps in SGT (UTC+8)
- Each signal has source tag and dedup_key

**After deduplication:**
- `CANVAS_DEADLINE_APPROACHING` passes (first time hitting "2_days" tier)
- `CALENDAR_GAP_DETECTED` passes (first time seeing this gap today)
- `MOOD_TREND_DOWN` passes (trend just shifted this cycle)
- `EMAIL_UNREAD_PILING` suppressed (already signaled at 12 PM when count hit 5)

**After enrichment:**
- Gap signal annotated: `suggested_task="CS2103 Assignment"`, `suggested_course="CS2103"`
- Mood signal annotated: `compounded_with=None` (not a busy day)

**Final output to Layer 2:** 3 enriched signals, sorted by urgency.

**What Layer 2 might generate:** "You've got a nice 2-hour window from 3 to 5 today — could be a good time to chip away at the CS2103 assignment (due tomorrow night). No rush, just putting it on your radar."

This message works because Layer 1 gave the Brain:
- The specific assignment and deadline
- The specific free time slot
- The mood context (so the Brain softens the tone — "no rush")
- Only 3 clean signals instead of 15 noisy duplicates
