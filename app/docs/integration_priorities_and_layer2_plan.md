# Integration Priorities & Layer 2 Design Plan

> **Audience**: NUS university students using Aura via WhatsApp
> **Context**: Layer 1 signal collection is largely built — dedup, enrichment, timezone, source tags, grade checking, Outlook support all implemented. This document prioritizes remaining integration work and designs the Layer 2 (Decision Engine) implementation.

---

## Part 1: Integration Prioritization

### Priority Framework

Every integration is scored on three axes:

- **Signal richness** — How many distinct, actionable signals can it produce?
- **Student impact** — How much does it affect the daily life of an NUS student?
- **Implementation effort** — How hard is it to build and maintain?

### Tier 1: High Priority (Wire Up Now)

These use APIs we already have access to. Minimal new auth, maximum signal value.

---

#### 1. Canvas Announcements & Discussions

**Why**: Professors post critical information in Canvas announcements — exam changes, lecture cancellations, project updates, grading rubric clarifications. Students who miss these get blindsided. Discussion deadlines are also graded work that the current system completely ignores.

**Endpoints to wire:**
```
GET /api/v1/announcements?context_codes[]=course_{id}
GET /api/v1/courses/{id}/discussion_topics
```

**New signals:**
- `CANVAS_ANNOUNCEMENT_NEW` — new announcement from professor (urgency: 7)
- `CANVAS_DISCUSSION_DUE` — discussion post/reply deadline approaching (urgency: 6)

**Effort**: Low. Same auth (Canvas PAT), same httpx client, just new endpoints.

**Dedup**: By announcement/discussion ID — emit once per item.

---

#### 2. Canvas Todo + Activity Stream

**Why**: Canvas has its own internal todo view (`/users/self/todo`) that aggregates across all courses — assignments, quizzes, discussions, peer reviews. The activity stream (`/users/self/activity_stream`) catches things our current `upcoming_events` call misses (like quiz submissions being due, or wiki page assignments).

**Endpoints to wire:**
```
GET /api/v1/users/self/todo
GET /api/v1/users/self/activity_stream
```

**New signals:**
- `CANVAS_TODO_ITEM` — Canvas's own prioritized todo (catches quizzes, peer reviews, etc.)
- `CANVAS_ACTIVITY_NEW` — new activity (submission comment, grade post, etc.)

**Effort**: Low. Both endpoints are user-scoped, no course iteration needed.

---

#### 3. Gmail Incremental Sync (`GMAIL_LIST_HISTORY`)

**Why**: Right now we re-fetch all unread emails every 5 minutes. `LIST_HISTORY` returns only changes since a `historyId`, making polling far more efficient and enabling true "new email arrived" detection vs "these emails are still unread."

**Composio slug**: `GMAIL_LIST_HISTORY`

**How to use it:**
1. After each poll, store the latest `historyId` in `signal_state` (key: `gmail_sync:latest_history_id`)
2. Next poll: call `LIST_HISTORY` with that ID
3. Only new/changed messages come back
4. Fall back to full `FETCH_EMAILS` if historyId is stale or first run

**Impact**: Fixes the "important emails re-fire" problem at the API level (not just dedup), reduces API calls by ~90%, and lets us detect truly NEW emails vs. already-seen-but-unread.

**Effort**: Medium. Need to manage historyId state, handle edge cases (expired history, account changes).

---

#### 4. Google Calendar Incremental Sync (`GOOGLECALENDAR_SYNC_EVENTS`)

**Why**: Same efficiency gain as Gmail. Instead of re-fetching all events every 5 min, only get changes. Also catches event edits (time change, cancellation) that the current system would miss until the next full refresh.

**Composio slug**: `GOOGLECALENDAR_SYNC_EVENTS`

**New signals enabled:**
- `CALENDAR_EVENT_CANCELLED` — event was deleted/cancelled
- `CALENDAR_EVENT_MOVED` — event time changed (critical for students with rescheduled lectures)

**State to manage**: `syncToken` per user, stored in `signal_state`.

**Effort**: Medium. Similar pattern to Gmail history sync.

---

#### 5. Google Calendar Multi-Calendar Support

**Why**: NUS students often have multiple calendars — personal, shared project calendars, NUS academic calendar (if subscribed), club calendars. Currently we only poll `primary`.

**Composio slugs**:
- `GOOGLECALENDAR_LIST_CALENDARS` — discover all calendars
- `GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS` — events across all

**Impact**: Catches group project meetings, club events, academic deadlines that students add via secondary calendars.

**Effort**: Low. Replace `calendar_id: "primary"` with discovered calendar IDs.

---

### Tier 2: Medium Priority (New Integrations for Students)

These require new authentication flows but unlock high-value signal sources for the university context.

---

#### 6. GitHub / GitLab (CS/Engineering Students)

**Why**: A huge portion of NUS students are in Computing or Engineering. They live in GitHub for project work. Signals from GitHub directly relate to coursework deadlines and group project coordination.

**Potential auth**: OAuth via Composio (GitHub is a supported integration) or Personal Access Token (like Canvas).

**Signals:**
- `GITHUB_PR_REVIEW_REQUESTED` — someone requested your review
- `GITHUB_ISSUE_ASSIGNED` — new issue assigned to you
- `GITHUB_PR_MERGED` / `GITHUB_PR_CHANGES_REQUESTED` — your PR got feedback
- `GITHUB_DEADLINE_APPROACHING` — issue/milestone with approaching due date
- `GITHUB_REPO_ACTIVITY` — teammates pushed commits (group project awareness)

**Cross-referencing**: GitHub milestones + Canvas assignment deadlines for the same course = unified project timeline.

**Effort**: Medium. Composio supports GitHub, so auth is handled. Need new signal collector + tool functions.

---

#### 7. Notion / Google Docs (Notes & Study Material)

**Why**: Many students use Notion or Google Docs for lecture notes, study planning, and group project documentation. Knowing what they're working on helps Donna be contextually relevant.

**Signals:**
- `NOTION_PAGE_SHARED` — collaborator shared a page with you
- `NOTION_REMINDER` — Notion's internal reminders
- `GDOCS_COMMENT_ADDED` — someone commented on your doc (group project coordination)

**Effort**: Medium-High. Notion API is well-documented, Google Docs via Composio. But the signal value is moderate — more useful for context enrichment than urgent signals.

---

#### 8. Telegram (Social Context)

**Why**: Telegram is extremely popular among NUS students for project group chats, module groups, and social coordination. While we can't (and shouldn't) read private messages, we could detect unread counts or channel activity if the user grants access.

**Signals:**
- `TELEGRAM_UNREAD_MENTIONS` — you were mentioned in a group
- `TELEGRAM_CHANNEL_ANNOUNCEMENT` — NUS-related channels posted something

**Effort**: High. Telegram Bot API or TDLib, complex auth, privacy considerations. Probably V2.

**Note**: This is sensitive territory — Donna should never read message contents from social apps. Only metadata (unread counts, mention detection).

---

#### 9. NUS Bus / Transport (MyTransport / LTA DataMall)

**Why**: NUS students spend a lot of time on campus shuttles and public transport. Knowing bus timings helps Donna time its "leave now" nudges.

**Data source**: LTA DataMall API (free, key-based auth) or NUS NextBus API.

**Signals:**
- `TRANSPORT_LEAVE_NOW` — based on calendar event location + transit time, "leave in 10 min to make it to your 2 PM at COM1"

**Cross-referencing**: Calendar event location + user's likely current location (campus if between classes) + transit time.

**Effort**: Medium. Free API, simple auth, but location inference is tricky.

---

#### 10. Spotify (Study & Wellbeing Context)

**Why**: Music listening patterns correlate with study sessions (lo-fi, focus playlists) and mood (sad music, hype music). This is contextual enrichment, not direct signals.

**Composio support**: Spotify is supported in Composio.

**Signals:**
- Not direct signals — more useful as context for the Brain layer ("user has been listening to focus music for 2 hours" = probably deep in study, don't interrupt)
- `SPOTIFY_LONG_SESSION` — listening for 2+ hours = likely studying

**Effort**: Low (Composio handles auth), but signal value is supplementary, not primary.

---

### Tier 3: Future Considerations (V2+)

| Integration | Signal Value | NUS Relevance | Notes |
|---|---|---|---|
| **NUS Library** (OPAC) | Book due dates, study room bookings | High | No public API, would need scraping |
| **Grabfood / FoodPanda** | Spending tracking, meal timing | Medium | No API, but could parse order confirmation emails |
| **Banking (DBS/OCBC)** | Budget alerts, spending patterns | High | No open API for SG banks, privacy concerns |
| **Zoom / Teams** | Meeting links, class recordings | Medium | Composio supports both |
| **Todoist / Ticktick** | External task management | Medium | Composio supports Todoist |
| **Google Fit / Apple Health** | Sleep, exercise, wellbeing | Medium | Privacy-sensitive, V2+ |

---

### NUSMods: Clarification on Usage

NUSMods is a **one-time ingestion**, not a recurring poll. Here's how it should work in the pipeline:

**Onboarding**: User pastes NUSMods share URL → Parse into structured timetable data → Store as:
1. `MemoryFact` entries with `category="timetable"` for each class slot (existing behavior)
2. `MemoryFact` entries with `category="exam"` for exam dates (needs to be added)

**Signal generation**: The `internal.py` collector should query these stored facts and emit:
- `NUSMODS_CLASS_APPROACHING` — class in 30 minutes (cross-reference with current time)
- `NUSMODS_EXAM_APPROACHING` — exam within 72/48/24 hours

**Not a recurring API call** — it's a DB-backed signal derived from stored timetable data, refreshed once per semester when the user re-shares their URL.

**Cross-referencing value:**
- NUSMods classes + Google Calendar = true free time (calendar might be empty but student has lectures)
- NUSMods exam dates + Canvas assignments = "your CS2103 exam is Thursday, and the final project is due Wednesday night — plan accordingly"
- NUSMods module codes + Canvas course matching = richer course context

---

### Unwired Composio Actions: What to Skip

Not everything available needs to be wired. Some actions are reactive-only (user asks Donna to do something) and don't generate signals:

**Wire for signals (proactive):**
- `GMAIL_LIST_HISTORY` — incremental sync
- `GOOGLECALENDAR_SYNC_EVENTS` — incremental sync
- `GOOGLECALENDAR_LIST_CALENDARS` — discover calendars
- `GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS` — multi-cal events

**Wire for reactive tools only (user-initiated):**
- `GMAIL_REPLY_TO_THREAD` — "reply to that email"
- `GMAIL_CREATE_EMAIL_DRAFT` — "draft a reply"
- `GOOGLECALENDAR_QUICK_ADD` — "add lunch with Alice tomorrow 1pm"
- `GOOGLECALENDAR_PATCH_EVENT` — "move my meeting to 3pm"
- `GOOGLECALENDAR_DELETE_EVENT` — "cancel that event"
- `GMAIL_FETCH_MESSAGE_BY_THREAD_ID` — "show me that email thread"
- `GMAIL_ADD_LABEL_TO_EMAIL` — "label those emails as project-X"

**Skip entirely (low value or risky):**
- `GMAIL_MOVE_TO_TRASH` — too risky for proactive action
- `GMAIL_GET_ATTACHMENT` — edge case, complex
- `GMAIL_FORWARD_MESSAGE` — risky, low demand
- `GMAIL_SEARCH_PEOPLE` / `GMAIL_GET_CONTACTS` — low signal value
- `GMAIL_GET_PROFILE` — one-time diagnostic, not ongoing
- `GOOGLECALENDAR_BATCH_EVENTS` — admin tool, not student-facing
- `GOOGLECALENDAR_GET_CALENDAR_PROFILE` — one-time timezone check only

---

## Part 2: Layer 2 — Decision Engine Design

### What Layer 2 Does

Layer 2 takes the deduplicated, enriched signal list from Layer 1 and decides:
1. **Should Donna say anything at all?** (most cycles: no)
2. **What should she say?** (candidate generation)
3. **Is NOW the right time?** (timing + rules)
4. **How should she say it?** (tone, format, channel)

### Current Implementation State

The current Layer 2 is split across three files:

| File | Role | Status |
|---|---|---|
| `donna/brain/context.py` | Builds full context window for LLM | Working, but context is kitchen-sink |
| `donna/brain/candidates.py` | LLM generates 0-3 scored candidates | Working, single-pass GPT-4o |
| `donna/brain/rules.py` | Score + filter (quiet hours, cooldown, cap, dedup) | Working, recently fixed `is_proactive` filter |

**What's missing** (from research):
1. **Rule-based pre-filter** — signals should be filtered BEFORE hitting the LLM, not after
2. **User model integration** — decisions should account for user's historical preferences
3. **Trust ramp** — new users get info-only, established users get nudges
4. **Self-threat framing** — avoid making the student feel corrected
5. **Action selection** — beyond "send message", Donna could offer buttons, schedule reminders, create calendar blocks
6. **Feedback loop** — learn from which messages the user engages with
7. **Reactive-only fallback** — if proactive confidence is low, save the insight for when the user next messages

### Target Architecture

```
Signals from L1 (max 10, deduplicated, enriched)
        │
        ▼
┌──────────────────────────────┐
│   STAGE 1: Rule Pre-Filter   │  ← No LLM. Fast. Cheap.
│                              │
│   • Drop signals below       │
│     minimum urgency for      │
│     this user's trust level  │
│   • Drop if user snoozed     │
│     this signal category     │
│   • Drop if daily theme      │
│     already covered          │
│   • Check quiet hours        │
│   • Check cooldown           │
│   • Check daily cap          │
│                              │
│   Output: 0-5 filtered       │
│   signals (or bail early)    │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│   STAGE 2: Context Assembly  │  ← DB queries
│                              │
│   • User profile + prefs     │
│   • Trust level + history    │
│   • Recent conversation      │
│   • Memory facts + recall    │
│   • Pending tasks            │
│   • Mood trajectory          │
│   • Behavioral patterns      │
│   • Feedback history         │
│   (what worked, what didn't) │
│                              │
│   Output: Context window     │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│   STAGE 3: LLM Generation    │  ← GPT-4o, single call
│                              │
│   • Generate 0-3 candidates  │
│   • Score each (relevance,   │
│     timing, urgency)         │
│   • Assign category + tone   │
│   • Suggest action type      │
│     (text, button, reminder) │
│   • Consider self-threat     │
│     framing                  │
│                              │
│   Output: Scored candidates  │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│   STAGE 4: Post-Filter       │  ← Rules, no LLM
│                              │
│   • Composite scoring        │
│     (relevance×timing×       │
│      urgency, weighted)      │
│   • Score threshold check    │
│   • Dedup vs recent messages │
│   • Trust-level gating       │
│   • Reactive-fallback check  │
│     (save for later if low   │
│      confidence)             │
│                              │
│   Output: 0-1 approved msg   │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│   STAGE 5: Delivery Routing  │  ← Already built in sender.py
│                              │
│   • 24h window check         │
│   • Freeform vs template     │
│   • Action buttons if        │
│     applicable               │
│   • Persist + log            │
│                              │
│   Output: Sent or deferred   │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│   STAGE 6: Feedback Capture  │  ← NEW
│                              │
│   • Track delivery outcome   │
│   • Wait for user response   │
│     (or silence)             │
│   • Update user model        │
│                              │
│   Output: Feedback record    │
└──────────────────────────────┘
```

### Stage-by-Stage Implementation

---

### Stage 1: Rule Pre-Filter (NEW)

**File**: `donna/brain/prefilter.py`

**Purpose**: Kill obvious non-starters before spending an LLM call. Currently, rules are applied AFTER the LLM generates candidates (in `rules.py`). This means we burn a GPT-4o call even when it's quiet hours or the daily cap is hit. Moving the hard-rule checks before the LLM saves cost and latency.

**What moves from `rules.py` to `prefilter.py`:**
- Quiet hours check
- Daily cap check (if already at 4, bail immediately)
- Cooldown check (if last proactive message was < 30 min ago, bail unless urgent signal)

**New pre-filter rules:**
- **Trust-level minimum urgency**: New users (< 2 weeks) only get signals with urgency >= 7. Established users see urgency >= 5.
- **Category snooze**: If user said "stop reminding me about X" or dismissed a similar message recently, suppress that signal category for a configurable period.
- **Daily theme dedup**: If we already sent a `deadline_warning` today, don't send another one unless urgency >= 8 (avoid being the nagging bot).

**Proposed interface:**
```python
async def prefilter_signals(
    user_id: str,
    signals: list[Signal],
    user_profile: dict,
) -> tuple[list[Signal], bool]:
    """Apply hard rules to signals before LLM generation.

    Returns:
        (filtered_signals, should_continue)
        If should_continue is False, skip the entire LLM pipeline.
    """
```

**Implementation sketch:**
```python
async def prefilter_signals(user_id, signals, user_profile):
    if not signals:
        return [], False

    # Check quiet hours
    if _in_quiet_hours(user_profile):
        urgent = [s for s in signals if s.urgency_hint >= 8]
        if not urgent:
            return [], False
        signals = urgent

    # Check daily cap
    sent_today = await count_proactive_today(user_id)
    if sent_today >= MAX_PROACTIVE_PER_DAY:
        return [], False

    # Check cooldown
    minutes_since = await _minutes_since_last_proactive(user_id)
    if minutes_since is not None and minutes_since < COOLDOWN_MINUTES:
        urgent = [s for s in signals if s.urgency_hint >= 8]
        if not urgent:
            return [], False
        signals = urgent

    # Trust-level gating
    trust_level = await _get_trust_level(user_id)
    min_urgency = _trust_urgency_threshold(trust_level)
    signals = [s for s in signals if s.urgency_hint >= min_urgency]

    # Category snooze
    signals = await _filter_snoozed(user_id, signals)

    if not signals:
        return [], False

    return signals, True
```

---

### Stage 2: Context Assembly (ENHANCE existing)

**File**: `donna/brain/context.py` (already exists)

**What to add:**

1. **Trust level**: Computed from account age + interaction count + feedback history.
```python
context["trust_level"] = {
    "level": "established",    # new | building | established | deep
    "days_active": 45,
    "total_interactions": 312,
    "proactive_acceptance_rate": 0.72,
}
```

2. **Feedback history**: Last 20 proactive messages and their outcomes.
```python
context["feedback_history"] = [
    {
        "category": "deadline_warning",
        "sent_at": "2025-02-10T14:00",
        "user_responded": True,
        "response_sentiment": "positive",
        "response_latency_minutes": 3,
    },
    # ...
]
```

3. **Behavioral patterns**: From `donna/memory/patterns.py` (already exists but not wired into context).
```python
context["behavioral_patterns"] = [
    "Usually starts studying after 9 PM",
    "Responds to deadline reminders within 5 minutes",
    "Ignores wellbeing check-ins on weekdays",
    "Prefers brief messages over detailed ones",
]
```

4. **User's current day shape**: Merge NUSMods timetable + calendar into a unified timeline.
```python
context["day_shape"] = {
    "classes": [{"module": "CS2103", "start": "10:00", "end": "12:00", "location": "COM1"}],
    "events": [{"title": "Team meeting", "start": "14:00", "end": "15:00"}],
    "free_blocks": [{"start": "12:00", "end": "14:00"}, {"start": "15:00", "end": "18:00"}],
    "deadlines_today": [{"title": "MA2001 Tutorial", "due": "23:59"}],
}
```

---

### Stage 3: LLM Generation (ENHANCE existing)

**File**: `donna/brain/candidates.py` (already exists)

**Changes to the system prompt:**

1. **Trust-level awareness**: Add trust level to the prompt so the LLM calibrates its approach.
```
The user's trust level is: {{trust_level}}
- "new" (< 2 weeks): Information only. Never suggest actions. Be helpful, not pushy.
- "building" (2-4 weeks): Gentle suggestions. Frame as options, not directives.
- "established" (1-3 months): Personalized nudges. Can reference past patterns.
- "deep" (3+ months): Full proactive planning. Can be direct about priorities.
```

2. **Self-threat framing guidelines**: From the research (Harari & Amir), unsolicited help triggers self-threat in users. Add this to the prompt:
```
CRITICAL FRAMING RULE:
Never make the user feel like you're correcting them or implying they can't manage.
- BAD: "You haven't started your CS2103 assignment yet and it's due tomorrow."
- GOOD: "CS2103 is due tomorrow night — you've got a solid 3-hour window after lunch if you want it."
- BAD: "You should exercise, your streak is about to break."
- GOOD: "Day 13 on the running streak — one more and you hit two weeks."

Frame everything as EQUIPPING (giving tools/info) not CORRECTING (pointing out failures).
```

3. **Action type selection**: Beyond just text messages, the LLM should suggest an action type:
```python
# New field in candidate output:
"action_type": "text" | "button_prompt" | "schedule_reminder" | "calendar_block" | "save_for_reactive"
```

- `text` — standard message
- `button_prompt` — message with quick-reply buttons ("Want me to block 2-4 PM for studying?" [Yes / Not now])
- `schedule_reminder` — don't send now, schedule for a specific time ("remind at 6 PM")
- `calendar_block` — offer to create a calendar event
- `save_for_reactive` — save this insight, surface it when the user next messages

4. **Feedback-aware generation**: Include recent feedback patterns so the LLM learns what works.
```
Recent feedback shows:
- Deadline reminders: 80% engagement (keep doing these)
- Wellbeing check-ins: 20% engagement on weekdays, 60% on weekends
- Study nudges: 45% engagement, higher when paired with specific time slots
- Email alerts: 70% engagement

Bias toward categories that get engagement. Reduce categories that get ignored.
```

---

### Stage 4: Post-Filter (REFACTOR existing)

**File**: `donna/brain/rules.py` (already exists)

**Changes:**

1. **Move hard rules to prefilter** (quiet hours, cooldown, daily cap) — Stage 1 handles these now.

2. **Keep in post-filter:**
   - Composite scoring (already working well)
   - Word-overlap dedup against recent messages (already working)
   - Final score threshold

3. **Add reactive-fallback logic:**
```python
# If the best candidate scores between 4.0 and 5.5, save it for reactive use
# instead of discarding it entirely
if best_score < SCORE_THRESHOLD and best_score >= REACTIVE_SAVE_THRESHOLD:
    await save_for_reactive(user_id, best_candidate)
    return []  # don't send proactively, but it's stored
```

4. **Trust-level score adjustment:**
```python
# New users need higher scores to trigger proactive messages
trust_threshold_map = {
    "new": 7.0,
    "building": 6.0,
    "established": 5.5,
    "deep": 5.0,
}
threshold = trust_threshold_map.get(trust_level, SCORE_THRESHOLD)
```

---

### Stage 5: Delivery Routing (ALREADY BUILT)

`donna/brain/sender.py` already handles:
- 24h window check (`_is_window_open`)
- Freeform vs template routing
- Template parameter extraction
- Button payloads
- Persist as `ChatMessage` with `is_proactive=True`

**Minor additions needed:**
- Handle `action_type == "button_prompt"` — use `send_whatsapp_buttons()` for interactive messages inside 24h window
- Handle `action_type == "schedule_reminder"` — create a one-off scheduled job instead of sending now
- Handle `action_type == "save_for_reactive"` — store in a `deferred_insights` table, surface in `context_loader` when user next messages

---

### Stage 6: Feedback Capture (NEW)

**File**: `donna/brain/feedback.py`

**Purpose**: Track what happens after Donna sends a proactive message. This closes the loop — Donna learns which types of messages the user engages with and which they ignore.

**Feedback signals:**

| Signal | Meaning | How to detect |
|---|---|---|
| User replied within 30 min | Positive engagement | Next user `ChatMessage` within 30 min of proactive message |
| User replied after 30 min | Neutral | Next message between 30 min and 6 hours |
| User didn't reply | Message was ignored | No user message within 6 hours |
| User said "stop" / "don't" | Negative feedback | NLP / keyword match on reply |
| User pressed button | Direct engagement | WhatsApp interactive reply callback |
| User acted on the suggestion | Strong positive | E.g., assignment submitted after deadline reminder |

**Data model:**
```python
class ProactiveFeedback(Base):
    __tablename__ = "proactive_feedback"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    message_id = Column(String, ForeignKey("chat_messages.id"), nullable=False)
    category = Column(String, nullable=False)        # deadline_warning, wellbeing, etc.
    trigger_signals = Column(JSON, nullable=True)     # which signals triggered this
    sent_at = Column(DateTime, nullable=False)
    outcome = Column(String, nullable=True)           # engaged, ignored, negative, button_click
    response_latency_seconds = Column(Integer, nullable=True)
    user_reply_snippet = Column(String, nullable=True)  # first 100 chars of reply
    created_at = Column(DateTime, default=func.now())
```

**Feedback collection flow:**
1. When `sender.py` sends a proactive message, also create a `ProactiveFeedback` row with `outcome=NULL`
2. When the user next messages (in `webhook.py` or `memory_writer`), check for pending feedback rows
3. Calculate response latency, determine outcome, update the row
4. If no response within 6 hours (checked by a lightweight scheduled job), mark as `ignored`

**How feedback flows back into decisions:**
- `context.py` aggregates recent feedback into engagement rates by category
- `candidates.py` prompt includes these rates so the LLM biases toward engaging categories
- `prefilter.py` can suppress categories with < 10% engagement rate over the last 30 days

---

### Trust Ramp Implementation

**How trust level is computed:**

```python
async def compute_trust_level(user_id: str) -> dict:
    """Compute the user's trust level based on interaction history."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return {"level": "new", "days_active": 0}

        days_active = (datetime.now(timezone.utc) - user.created_at).days

        # Count total user messages
        msg_count = await session.execute(
            select(func.count(ChatMessage.id))
            .where(ChatMessage.user_id == user_id, ChatMessage.role == "user")
        )
        total_interactions = msg_count.scalar_one()

        # Count proactive engagement rate
        feedback_result = await session.execute(
            select(ProactiveFeedback)
            .where(ProactiveFeedback.user_id == user_id)
            .order_by(ProactiveFeedback.created_at.desc())
            .limit(50)
        )
        feedbacks = feedback_result.scalars().all()
        engaged = sum(1 for f in feedbacks if f.outcome == "engaged")
        acceptance_rate = engaged / len(feedbacks) if feedbacks else 0.5

    # Determine level
    if days_active < 14 or total_interactions < 20:
        level = "new"
    elif days_active < 30 or total_interactions < 100:
        level = "building"
    elif days_active < 90:
        level = "established"
    else:
        level = "deep"

    return {
        "level": level,
        "days_active": days_active,
        "total_interactions": total_interactions,
        "proactive_acceptance_rate": round(acceptance_rate, 2),
    }
```

**Trust level behavior changes:**

| Aspect | new | building | established | deep |
|---|---|---|---|---|
| **Message types** | Info only | Info + gentle suggestions | Personalized nudges | Proactive planning |
| **Score threshold** | 7.0 | 6.0 | 5.5 | 5.0 |
| **Daily cap** | 2 | 3 | 4 | 5 |
| **Min urgency** | 7 | 6 | 5 | 4 |
| **Action types** | Text only | Text + buttons | All except calendar_block | All |
| **Tone** | Warm, careful | Warm, occasionally direct | Natural, personality shows | Full Donna personality |
| **Framing** | Pure information | "You might want to..." | Direct suggestions | Anticipatory planning |

---

### Reactive Fallback System

**The idea**: Not every insight is worth a proactive message. But if Donna noticed something interesting (e.g., "your mood has been up this week" or "you have a free evening and mentioned wanting to try that ramen place"), she can save it and bring it up naturally when the user next messages her.

**Data model:**
```python
class DeferredInsight(Base):
    __tablename__ = "deferred_insights"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String, nullable=False)
    message_draft = Column(String, nullable=False)    # the candidate that wasn't sent
    trigger_signals = Column(JSON, nullable=True)
    relevance_score = Column(Float, nullable=False)
    created_at = Column(DateTime, default=func.now())
    expires_at = Column(DateTime, nullable=False)     # insight becomes stale after X hours
    used = Column(Boolean, default=False)
```

**How it works:**
1. `rules.py` post-filter saves borderline candidates (score 4.0–5.5) as `DeferredInsight`
2. When the user messages Donna reactively, `context_loader` (agent node) queries `DeferredInsight` for fresh, unused insights
3. These insights are injected into the `response_composer` context as "things Donna noticed"
4. The composer can naturally weave them in: user asks "what's up?" → Donna replies to their question AND mentions "oh also, I noticed you've got a clear evening and you mentioned wanting to try that new ramen place"

---

### Implementation Order

**Phase 1: Pre-filter (saves money immediately)**
1. Create `donna/brain/prefilter.py` with hard-rule checks
2. Wire into `donna/loop.py` between `collect_all_signals` and `build_context`
3. Move quiet hours, cooldown, daily cap from `rules.py` to `prefilter.py`
4. `rules.py` keeps: composite scoring, word dedup, final threshold

**Phase 2: Trust ramp**
5. Add `compute_trust_level()` to a new `donna/brain/trust.py`
6. Wire into `prefilter.py` for urgency gating
7. Wire into `context.py` to include trust level in LLM context
8. Update `candidates.py` system prompt with trust-level instructions
9. Make daily cap and score threshold trust-dependent in `rules.py`

**Phase 3: Enhanced context**
10. Wire behavioral patterns from `donna/memory/patterns.py` into `build_context()`
11. Add day-shape computation (NUSMods timetable + calendar merged)
12. Add feedback history to context (requires Phase 4 data)

**Phase 4: Feedback loop**
13. Create `ProactiveFeedback` model in `db/models.py`
14. Create `donna/brain/feedback.py` with feedback tracking logic
15. Hook into `sender.py` (create feedback row on send)
16. Hook into `webhook.py` / `memory_writer` (update feedback on user reply)
17. Add lightweight scheduler job for "mark as ignored after 6h"
18. Wire aggregated feedback into `build_context()`

**Phase 5: Reactive fallback**
19. Create `DeferredInsight` model
20. Save borderline candidates in `rules.py`
21. Query deferred insights in `agent/nodes/context.py`
22. Update `composer.py` prompt to weave in deferred insights

**Phase 6: Advanced LLM prompt**
23. Add self-threat framing guidelines to `candidates.py` prompt
24. Add action type selection to candidate output format
25. Handle new action types in `sender.py` (buttons, schedule, calendar block)
26. Add feedback-aware prompt section

**Phase 7: Prompt optimization (ongoing)**
27. A/B test prompt variations
28. Tune scoring weights based on feedback data
29. Consider using a lighter model (GPT-4o-mini) for pre-screening, GPT-4o for final generation

---

### Cost Estimates

Current: Every 5-min cycle for every user = 1 GPT-4o call (candidate generation) + context query

| Users | Cycles/day | GPT-4o calls/day | Est. cost/day |
|---|---|---|---|
| 10 | 2,880 | 2,880 | ~$14 (at ~$0.005/call avg) |
| 100 | 28,800 | 28,800 | ~$144 |
| 1,000 | 288,000 | 288,000 | ~$1,440 |

**With pre-filter (Stage 1)**: ~80% of cycles should bail before LLM call (quiet hours, no signals, cooldown). Reduces cost by 5x.

| Users | After pre-filter | Est. cost/day |
|---|---|---|
| 10 | ~576 | ~$3 |
| 100 | ~5,760 | ~$29 |
| 1,000 | ~57,600 | ~$288 |

**With GPT-4o-mini for screening** (Phase 7): Additional 2-3x cost reduction.

---

### Key Files to Create / Modify

| File | Action | Phase |
|---|---|---|
| `donna/brain/prefilter.py` | **CREATE** | Phase 1 |
| `donna/brain/trust.py` | **CREATE** | Phase 2 |
| `donna/brain/feedback.py` | **CREATE** | Phase 4 |
| `donna/loop.py` | **MODIFY** — insert prefilter step | Phase 1 |
| `donna/brain/rules.py` | **MODIFY** — move hard rules out, add reactive fallback | Phase 1, 5 |
| `donna/brain/context.py` | **MODIFY** — add trust, feedback, patterns, day_shape | Phase 2, 3 |
| `donna/brain/candidates.py` | **MODIFY** — enhanced prompt | Phase 2, 6 |
| `donna/brain/sender.py` | **MODIFY** — handle new action types | Phase 6 |
| `db/models.py` | **MODIFY** — add ProactiveFeedback, DeferredInsight | Phase 4, 5 |
| `agent/nodes/context.py` | **MODIFY** — query deferred insights | Phase 5 |
| `agent/nodes/composer.py` | **MODIFY** — weave in deferred insights | Phase 5 |
