# Layer 2: Decision Engine — Architecture & Implementation Guide

> **Purpose**: This document is the definitive reference for Donna's Decision Engine — the brain layer that decides *what* to say, *when* to say it, and *how* to say it. It covers the full pipeline from pre-filtering through trust-aware candidate generation, scoring, feedback tracking, and reactive fallback.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Pipeline Architecture](#2-pipeline-architecture)
3. [Phase 1: Pre-filter](#3-phase-1-pre-filter)
4. [Phase 2: Trust Ramp](#4-phase-2-trust-ramp)
5. [Phase 3: Feedback Loop](#5-phase-3-feedback-loop)
6. [Phase 4: Reactive Fallback](#6-phase-4-reactive-fallback)
7. [Phase 5: Enhanced LLM Prompt](#7-phase-5-enhanced-llm-prompt)
8. [Data Models](#8-data-models)
9. [File Map](#9-file-map)
10. [Testing](#10-testing)

---

## 1. Overview

Layer 2 sits between Layer 1 (Signal Collection) and the WhatsApp delivery. It answers three questions every 5 minutes per user:

1. **Should we even think about messaging?** (Pre-filter — hard rules, no LLM cost)
2. **What should Donna say?** (Context + LLM candidates + scoring)
3. **Did the user care?** (Feedback loop — learning from engagement)

### Problem Statement

Before Layer 2, the brain had several gaps:

| Problem | Impact | Solution |
|---|---|---|
| Hard rules checked AFTER LLM call | Wasted ~80% of LLM spend | Pre-filter (Phase 1) |
| New users treated same as established | Overwhelmed/annoyed new users | Trust ramp (Phase 2) |
| No learning from engagement | Same mistakes repeated | Feedback loop (Phase 3) |
| Borderline insights discarded | Lost value from "almost good" candidates | Reactive fallback (Phase 4) |
| No self-threat framing | Users felt corrected, not helped | Enhanced prompt (Phase 5) |

### Pipeline Flow (after Layer 2)

```
collect_all_signals()         → Signal[]
  ↓
prefilter_signals()           → (Signal[], should_continue, trust_info)
  ↓  [bail if should_continue=False]
context-only check            → bail if no concrete signals
  ↓
build_context()               → dict (includes trust, feedback, patterns)
  ↓
generate_candidates()         → Candidate[] (trust-aware LLM prompt)
  ↓
score_and_filter()            → Approved[] + Deferred[]
  ↓
save_deferred_insights()      → DeferredInsight rows (borderline candidates)
  ↓
send_proactive_message()      → WhatsApp (freeform or template) + feedback record
```

---

## 2. Pipeline Architecture

### Entry Point: `donna/loop.py`

The main loop orchestrates the full pipeline for a single user:

```python
async def donna_loop(user_id: str) -> int:
    # 1. Collect signals (calendar, canvas, email, internal)
    signals = await collect_all_signals(user_id)
    if not signals:
        return 0

    # 1b. Pre-filter: hard rules BEFORE LLM
    signals, should_continue, trust_info = await prefilter_signals(user_id, signals)
    if not should_continue:
        return 0

    # 1c. Skip if only context-only signals
    has_concrete = any(not s.data.get("_context_only") for s in signals)
    if not has_concrete:
        return 0

    # 2. Build context window for the LLM
    context = await build_context(user_id, signals, trust_info=trust_info)

    # 3. Generate candidate messages via LLM
    candidates = await generate_candidates(context)
    if not candidates:
        return 0

    # 4. Score, filter, and save deferred insights
    approved = score_and_filter(candidates, context)
    await save_deferred_insights(user_id, context)

    if not approved:
        return 0

    # 5. Send top message only
    best = approved[0]
    sent = await send_proactive_message(user_id, best)
    return 1 if sent else 0
```

Key design decision: **only one message per cycle**. Even if multiple candidates pass, we send only the highest-scoring one to avoid overwhelming the user.

---

## 3. Phase 1: Pre-filter

**File**: `donna/brain/prefilter.py`

### Purpose

Move hard-rule checks to run **before** the LLM call. This skips the most expensive part of the pipeline (~80% of cycles) when rules would block delivery anyway.

### Hard Rules (checked in order)

#### 1. Trust-based Urgency Filter

Signals below the trust level's `min_urgency` threshold are dropped. This prevents low-importance signals from triggering expensive LLM calls for users who haven't built enough trust.

```python
filtered_signals = [s for s in signals if s.urgency_hint >= min_urgency]
```

If no signals survive and none were urgent (>=8), the cycle stops.

#### 2. Quiet Hours

Uses the user's `wake_time` and `sleep_time` (from their profile) plus their timezone to determine if it's currently quiet hours. During quiet hours, only signals with `urgency_hint >= 8` can pass through.

```
User sleep_time=23:00, wake_time=08:00 → 23:00–08:00 is quiet
Current local time = 02:00 → BLOCKED (unless urgent)
```

#### 3. Daily Cap

Counts proactive messages sent today (UTC) via `count_proactive_today()`. If at or above the trust-dependent cap, the cycle stops.

#### 4. Cooldown

Checks the timestamp of the most recent proactive `ChatMessage`. If it was sent less than 30 minutes ago and no signals are urgent, the cycle stops.

```python
COOLDOWN_MINUTES = 30
URGENT_SIGNAL_THRESHOLD = 8
```

### Bypass: Urgent Signals

Any signal with `urgency_hint >= 8` bypasses quiet hours AND cooldown (but not daily cap). This ensures truly time-sensitive events (assignment due in 1 hour, important email) still get through.

### Return Signature

```python
async def prefilter_signals(
    user_id: str,
    signals: list[Signal],
    user_tz: str = "UTC",
) -> tuple[list[Signal], bool, dict]:
    """Returns (filtered_signals, should_continue, trust_info)"""
```

The `trust_info` dict is passed downstream so the loop doesn't recompute it.

---

## 4. Phase 2: Trust Ramp

**File**: `donna/brain/trust.py`

### Purpose

New users shouldn't receive the same volume and variety of proactive messages as users who've been on the platform for months. The trust ramp gradually increases Donna's proactive behavior as the relationship deepens.

### Trust Level Computation

Two inputs determine trust level:
- **`days_active`**: Days since `User.created_at`
- **`total_interactions`**: Count of `ChatMessage` rows where `role="user"`

```python
if days_active < 14 or total_interactions < 20:
    level = "new"
elif days_active < 30 or total_interactions < 100:
    level = "building"
elif days_active < 90:
    level = "established"
else:
    level = "deep"
```

The OR logic means both conditions must be met to graduate. A user who signed up 30 days ago but only sent 15 messages stays "new."

### Trust-Dependent Configuration

| Level | Score Threshold | Daily Cap | Min Urgency | Behavior |
|---|---|---|---|---|
| **new** | 7.0 | 2 | 7 | Only high-value, time-sensitive signals |
| **building** | 6.0 | 3 | 6 | Schedule + deadline signals |
| **established** | 5.5 | 4 | 5 | Full proactive behavior |
| **deep** | 5.0 | 5 | 4 | Maximum engagement, personality |

### Where Trust Is Used

1. **Pre-filter** (`prefilter.py`): `min_urgency` filters signals, `daily_cap` limits sends
2. **Context** (`context.py`): `trust_info` included in LLM context, `score_threshold` set from trust
3. **Candidates** (`candidates.py`): LLM prompt includes trust-level instructions (conservative for new users, full personality for deep)
4. **Rules** (`rules.py`): Score threshold is trust-dependent via `context["score_threshold"]`

### LLM Trust Instructions

The candidate generator dynamically appends trust-level instructions to the system prompt:

- **New**: "Be conservative. Only message for clearly time-sensitive signals. Err on the side of silence."
- **Building**: "Moderate approach. Can surface schedule optimizations and deadlines."
- **Established**: "Normal proactive behavior. Full range of message types."
- **Deep**: "Can be more direct and witty. Proactive about subtle patterns."

---

## 5. Phase 3: Feedback Loop

**Files**: `donna/brain/feedback.py`, `db/models.py` (ProactiveFeedback)

### Purpose

Track which proactive messages users engage with vs. ignore, so Donna can learn which categories work and adjust.

### Data Model: `ProactiveFeedback`

```
proactive_feedback
├── id (String PK)
├── user_id (FK → users.id)
├── message_id (String) — links to the ChatMessage
├── category (String) — e.g., "deadline_warning", "briefing"
├── trigger_signals (JSON) — signal types that triggered this
├── sent_at (DateTime)
├── outcome (String) — "pending" | "engaged" | "ignored" | "negative" | "button_click"
├── response_latency_seconds (Float, nullable)
└── created_at (DateTime)
```

### Lifecycle

```
1. Donna sends message → record_proactive_send() → outcome="pending"
                             ↓
2a. User replies within 60min → check_and_update_feedback() → outcome="engaged"
                             ↓
2b. No reply after 180min → check_and_update_feedback() → outcome="ignored"
```

### Three Functions

#### `record_proactive_send(user_id, message_id, candidate)`
Called by `sender.py` after successful delivery. Creates a `ProactiveFeedback` row with `outcome="pending"`.

#### `check_and_update_feedback(user_id)`
Called by `agent/nodes/memory.py` when the user sends a message (reactive path). Checks:
- **Recent pending** (sent within 60 min): Mark as `"engaged"`, record response latency
- **Old pending** (sent > 180 min ago): Mark as `"ignored"`

#### `get_feedback_summary(user_id, days=30)`
Called by `context.py` when building the brain context. Returns:
```python
{
    "total_sent": 12,
    "engaged": 8,
    "ignored": 3,
    "engagement_rate": 0.67,
    "engagement_by_category": {
        "deadline_warning": 0.9,
        "briefing": 0.5,
        "memory_recall": 0.33,
    },
    "avg_response_latency_seconds": 342.5,
}
```

### How Feedback Informs the LLM

The candidate generator includes a feedback section in the system prompt when data exists:

```
FEEDBACK DATA (last 30 days):
Total messages sent: 12
Overall engagement rate: 67%
Engagement by category:
  - deadline_warning: 90% engagement
  - briefing: 50% engagement
  - memory_recall: 33% engagement
Prioritize categories with higher engagement.
Avoid categories the user consistently ignores.
```

This gives the LLM real data to shape its candidate generation — more deadline warnings (90% hit rate), fewer memory recalls (33%).

---

## 6. Phase 4: Reactive Fallback

**Files**: `donna/brain/rules.py`, `db/models.py` (DeferredInsight), `agent/nodes/context.py`, `agent/nodes/composer.py`

### Purpose

When the proactive pipeline produces candidates that are *almost* good enough (score 4.0–5.5) but don't pass the threshold, save them as **deferred insights** instead of discarding them. Surface them when the user next messages Donna, weaving them naturally into the reply.

### Data Model: `DeferredInsight`

```
deferred_insights
├── id (String PK)
├── user_id (FK → users.id)
├── category (String)
├── message_draft (Text) — the original LLM-generated message
├── trigger_signals (JSON)
├── relevance_score (Float) — composite score from rules.py
├── created_at (DateTime)
├── expires_at (DateTime) — 24h after creation
└── used (Boolean, default False)
```

### Proactive Side: Saving Deferred Candidates

In `rules.py`, `score_and_filter()` collects candidates that score between `DEFERRED_MIN_SCORE` (4.0) and the trust-dependent threshold:

```python
if composite < threshold:
    if composite >= DEFERRED_MIN_SCORE:
        deferred.append(candidate)
    continue
```

After scoring, the loop calls `save_deferred_insights()` which persists them with a 24-hour expiry.

### Reactive Side: Surfacing Insights

When the user sends a message, the reactive pipeline's `context_loader()` in `agent/nodes/context.py` queries fresh, unused deferred insights:

```python
select(DeferredInsight)
    .where(
        DeferredInsight.user_id == user_id,
        DeferredInsight.used.is_(False),
        DeferredInsight.expires_at >= now,
    )
    .order_by(DeferredInsight.relevance_score.desc())
    .limit(3)
```

Retrieved insights are marked `used = True` and added to the context as `deferred_insights`.

The response composer in `agent/nodes/composer.py` adds them to the LLM prompt:

```
Things Donna noticed recently (weave naturally if relevant):
- [deadline_warning] CS2103 is due tomorrow — you've got a 3-hour window after lunch.
- [memory_recall] Wasn't there that chimichanga place you wanted to try?
```

The composer's system prompt tells the LLM to weave these naturally, not dump them. If the user said "hey, how's my week looking?", Donna might work in the deadline mention. If the user said "what should I eat?", the restaurant memory would surface.

---

## 7. Phase 5: Enhanced LLM Prompt

**Files**: `donna/brain/candidates.py`, `donna/brain/sender.py`

### Self-Threat Framing Rule

Added to the system prompt to prevent messages that make users feel corrected or judged:

```
SELF-THREAT FRAMING RULE:
Never make the user feel corrected, judged, or behind.
Frame every message as EQUIPPING (giving info/tools/options) not CORRECTING (pointing out failures).

BAD: "You haven't started your assignment yet."
GOOD: "CS2103 is due tomorrow — you've got a 3-hour window after lunch."

BAD: "You missed your workout again."
GOOD: "Gym's open till 10pm tonight if you want to squeeze one in."
```

This is a critical voice principle: Donna is a sharp friend who *equips*, not a nagging parent who *corrects*.

### Action Type: Button Prompts

Candidates can now specify `action_type: "button_prompt"` for messages that naturally invite a yes/no response:

```json
{
  "message": "CS2030S Lab 4 due tomorrow. Want me to block 2-5pm?",
  "action_type": "button_prompt"
}
```

The sender routes these differently inside the 24h WhatsApp window:

```python
if action_type == "button_prompt":
    await send_whatsapp_buttons(
        to=user.phone,
        body=message_text,
        buttons=[
            {"id": "btn_yes", "title": "Yes"},
            {"id": "btn_later", "title": "Later"},
        ],
    )
else:
    await send_whatsapp_message(to=user.phone, text=message_text)
```

Outside the 24h window, all messages fall back to approved templates regardless of action type.

### Dynamic Prompt Composition

The system prompt is now composed of three parts:

```python
system = SYSTEM_PROMPT + _build_trust_instructions(context) + _build_dynamic_sections(context)
```

1. **Base prompt**: Core rules, voice, scoring guide, self-threat framing
2. **Trust instructions**: Level-specific calibration (conservative → full personality)
3. **Dynamic sections**: Feedback data + behavioral patterns (from memory facts with `category="pattern"`)

---

## 8. Data Models

### ProactiveFeedback

Tracks engagement with proactive messages for the feedback loop.

| Column | Type | Description |
|---|---|---|
| id | String (PK) | UUID |
| user_id | String (FK) | Links to users table |
| message_id | String | Links to the ChatMessage that was sent |
| category | String | Candidate category (deadline_warning, briefing, etc.) |
| trigger_signals | JSON | Signal types that caused this message |
| sent_at | DateTime | When the proactive message was delivered |
| outcome | String | pending → engaged / ignored / negative / button_click |
| response_latency_seconds | Float | Time between send and user reply (if engaged) |
| created_at | DateTime | Row creation time |

### DeferredInsight

Stores borderline proactive candidates for reactive surfacing.

| Column | Type | Description |
|---|---|---|
| id | String (PK) | UUID |
| user_id | String (FK) | Links to users table |
| category | String | Candidate category |
| message_draft | Text | The LLM-generated message text |
| trigger_signals | JSON | Signal types that triggered this candidate |
| relevance_score | Float | Composite score from rules.py |
| created_at | DateTime | When the insight was saved |
| expires_at | DateTime | 24h after creation — auto-expires |
| used | Boolean | True once surfaced in a reactive reply |

---

## 9. File Map

### New Files (Created)

| File | Phase | Purpose |
|---|---|---|
| `donna/brain/prefilter.py` | 1, 2 | Hard rules before LLM: quiet hours, daily cap, cooldown, trust urgency filter |
| `donna/brain/trust.py` | 2 | Trust level computation (new → building → established → deep) |
| `donna/brain/feedback.py` | 3 | Record sends, check engagement, generate feedback summaries |
| `tests/donna/brain/test_prefilter.py` | 1 | 11 tests: quiet hours, daily cap, cooldown, trust filtering |
| `tests/donna/brain/test_trust.py` | 2 | 7 tests: all levels, boundaries, missing user |
| `tests/donna/brain/test_feedback.py` | 3 | 5 tests: record, engage, ignore, summary |

### Modified Files

| File | Phases | Changes |
|---|---|---|
| `donna/loop.py` | 1, 2, 4 | Inserted prefilter, context-only check, deferred insight saving |
| `donna/brain/rules.py` | 1, 4 | Removed hard rules (now in prefilter), added deferred candidate collection, trust-dependent threshold |
| `donna/brain/context.py` | 2, 3 | Added trust_info, behavioral patterns, feedback summary to context |
| `donna/brain/candidates.py` | 2, 3, 5 | Trust instructions, feedback data, self-threat framing, action_type field |
| `donna/brain/sender.py` | 3, 5 | Feedback recording after send, button_prompt handling |
| `donna/signals/base.py` | 1 | Added CALENDAR_BUSY_DAY and CALENDAR_EMPTY_DAY to medium urgency (5) |
| `db/models.py` | 3, 4 | Added ProactiveFeedback and DeferredInsight models |
| `agent/nodes/context.py` | 4 | Query and surface deferred insights in reactive path |
| `agent/nodes/composer.py` | 4 | Weave deferred insights into reactive replies |
| `agent/nodes/memory.py` | 3 | Call check_and_update_feedback() on user message |
| `tests/conftest.py` | 1, 3 | New model imports, session patches for new modules |
| `tests/donna/brain/test_scorer.py` | 1 | Removed hard-rule tests (moved to prefilter), added trust threshold test |
| `tests/donna/test_full_loop.py` | 1, 2 | Trust mocking, daytime patch target, user messages for 24h window |

---

## 10. Testing

### Test Suite Summary (60 tests, all passing)

```
tests/donna/brain/test_feedback.py     — 5 tests  (feedback loop)
tests/donna/brain/test_prefilter.py    — 11 tests (hard rules)
tests/donna/brain/test_scorer.py       — 8 tests  (scoring + dedup)
tests/donna/brain/test_trust.py        — 7 tests  (trust levels)
tests/donna/signals/test_dedup.py      — 5 tests  (signal dedup)
tests/donna/signals/test_enrichment.py — 4 tests  (signal enrichment)
tests/donna/signals/test_internal.py   — 9 tests  (internal signals)
tests/donna/test_full_loop.py          — 8 tests  (end-to-end pipeline)
```

### Key Test Patterns

**Trust Isolation**: Pre-filter and full-loop tests mock `compute_trust_level` to return "established" config, isolating hard-rule behavior from trust logic. Trust-specific filtering has its own dedicated test (`test_trust_min_urgency_filters`).

**WhatsApp 24h Window**: Full-loop tests that expect message delivery add a recent user message to the DB so the sender takes the freeform (mocked) path instead of the template path.

**UTC Datetime Handling**: Tests use `datetime.now(timezone.utc)` with minute-level offsets (not hours) to avoid UTC day boundary issues when the test machine is in a non-UTC timezone (e.g., SGT = UTC+8).

### Running Tests

```bash
cd /Users/i3dlab/Documents/NUS/bakchodi/aura/app

# Lint
ruff check . --target-version py311 --line-length 100

# Tests
pytest tests/ -v --asyncio-mode=auto
```

### Manual Verification Checklist

1. **Pre-filter savings**: Run `donna_loop` during quiet hours → verify LLM NOT called (check logs for "Prefilter: quiet hours")
2. **Trust ramp**: New user (< 14 days, < 20 messages) → verify higher score threshold (7.0) and lower daily cap (2)
3. **Feedback tracking**: Send proactive message → user replies within 60 min → verify `ProactiveFeedback.outcome = "engaged"`
4. **Deferred insights**: Candidate scores 4.5 (below 5.5 threshold) → verify `DeferredInsight` created → user messages Donna → insight appears in context
5. **Button prompts**: Candidate with `action_type="button_prompt"` inside 24h window → verify WhatsApp interactive reply buttons sent
