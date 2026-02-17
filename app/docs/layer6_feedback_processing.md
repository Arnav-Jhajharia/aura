# Layer 6: Feedback Processing — Architecture & Implementation Plan

> **What Layer 6 does**: Closes the loop. Every proactive message Donna sends generates an outcome — the student replies, taps a button, reads but ignores, or never sees it. Layer 6 captures these outcomes, learns from them, and feeds the learning back into Layers 2-5 so Donna gets better for each individual student over time.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Current State Audit](#2-current-state-audit)
3. [The Feedback Loop Architecture](#3-the-feedback-loop-architecture)
4. [Signal Capture: What Counts as Feedback](#4-signal-capture-what-counts-as-feedback)
5. [Outcome Classification](#5-outcome-classification)
6. [Per-User Learning: What Donna Adapts](#6-per-user-learning-what-donna-adapts)
7. [Feedback → Layer Integration](#7-feedback--layer-integration)
8. [Nightly Reflection Integration](#8-nightly-reflection-integration)
9. [Anti-Patterns & Safety Rails](#9-anti-patterns--safety-rails)
10. [Implementation Plan](#10-implementation-plan)

---

## 1. The Problem

Most proactive messaging systems treat feedback as an afterthought — you send messages, check a dashboard, maybe adjust a threshold. Donna can't afford this. She's texting students on WhatsApp, which is their most personal communication channel. Every bad message costs trust. Every ignored message is a data point that should make the next one better.

The research is specific about what makes feedback loops work in proactive systems:

- **ComPeer (2024)**: Fixed-interval messages were universally disliked. But the same messages, sent at moments the user had historically engaged, were received positively. The difference was the system's ability to learn WHEN.
- **Harari & Amir (self-threat theory)**: Users who received messages framed as corrections disengaged within 2 weeks. Users who received the same information framed as equipping maintained engagement for 3+ months. The difference was the system's ability to learn HOW.
- **Behavioral retention**: Users who see a system "learn" their patterns (message timing adapts, irrelevant categories disappear) report 2.3× higher satisfaction than users with static systems.

The current feedback system captures the basic signal (replied = engaged, didn't reply = ignored). But it doesn't USE the signal to change behavior. The engagement rate by category is computed and passed to the LLM — but the LLM is stateless. It sees the numbers, maybe adjusts this cycle, but has no persistent learning. The real adaptation has to happen in code: adjusting thresholds, timing, format preferences, and category weights based on accumulated evidence.

---

## 2. Current State Audit

### `donna/brain/feedback.py` — The feedback recorder

**What it does well:**
- `record_proactive_send()` creates a `ProactiveFeedback` row immediately after send, with category and trigger signals
- `check_and_update_feedback()` is called from `memory_writer` on every user message — marks recent pending messages as "engaged" if the user replied within 60 minutes
- Times out old pending entries as "ignored" after 180 minutes
- `get_feedback_summary()` computes per-category engagement rates over 30 days
- Tracks `response_latency_seconds` — how fast the user replied
- Handles `button_click` as a distinct outcome alongside `engaged`

**What's missing:**

1. **No "negative" outcome capture**. If a user replies to a proactive message with "stop", "please don't", "not helpful", or an annoyed tone, the feedback system marks it as "engaged" (they replied!). This is actively wrong — negative engagement should suppress that category, not reinforce it.

2. **No "read but ignored" vs "never delivered"**. Currently, any pending entry that times out becomes "ignored." But there's a massive difference between: (a) message delivered + read + user chose not to reply, (b) message delivered but not read, and (c) message never delivered (phone off, network error). With Layer 5's delivery status tracking, we'll have this data — Layer 6 needs to use it.

3. **No format feedback**. We don't know if the user engaged because it was a button message (easy to tap) or despite it being plain text. Format preference learning requires tracking which format was used alongside the outcome.

4. **No time-of-day feedback**. If Donna sends deadline reminders at 10 AM and the user always ignores them, but the one sent at 8 PM gets a reply, the system should learn that this user prefers evening messages. Currently, `sent_at` is stored but never analyzed for time-of-day patterns.

5. **Feedback summary is compute-every-time**. `get_feedback_summary()` scans all entries from the last 30 days on every proactive cycle. For a user with 4 messages/day × 30 days = 120 rows, this is fine. But it's an O(n) scan that could be pre-computed in nightly reflection.

6. **No feedback decay**. A message sent 29 days ago counts equally to one sent yesterday. Recent feedback should weigh more — the user's preferences shift over a semester.

### `donna/brain/rules.py` — Where feedback meets decisions

**What it does well:**
- Passes `feedback_summary` into the LLM context so the model can see engagement rates
- Composite scoring weights (relevance 0.4, timing 0.35, urgency 0.25) are reasonable
- Trust-dependent threshold allows new users to have a higher bar

**What's missing:**

1. **Feedback doesn't adjust weights**. The scoring weights are hardcoded. If a user consistently engages with urgent messages but ignores timing-optimized ones, the urgency weight should increase for that user.

2. **No category suppression**. If `wellbeing` messages have 0% engagement over 2 weeks (5+ attempts), the system should stop sending them. Currently, the LLM sees "wellbeing: 0% engagement" in the prompt but may still generate wellbeing candidates.

3. **No "earned back" mechanism**. Once a category is suppressed, how does it come back? A user who hated wellbeing check-ins in Week 2 might welcome them in Week 8 after building trust. Need a probationary re-introduction system.

### `donna/brain/candidates.py` — Where feedback is consumed

**What it does well:**
- `_build_dynamic_sections()` injects engagement rates per category into the system prompt
- The prompt tells the LLM: "Prioritize categories with higher engagement. Avoid categories the user consistently ignores."
- Behavioral patterns from nightly reflection are injected

**What's missing:**

1. **LLM has no memory across cycles**. The LLM sees "deadline_warning: 80% engagement, wellbeing: 10% engagement" but doesn't know if this is improving, stable, or declining. Trend direction matters: wellbeing at 10% but rising (user warming up) is different from wellbeing at 10% and falling (user increasingly annoyed).

2. **No per-signal feedback**. The LLM knows category-level engagement but not signal-level. "Canvas deadline reminders" might get 90% engagement while "internal task reminders" get 20% — both are `deadline_warning` category. Need signal-type granularity.

### `donna/reflection.py` — Nightly batch processing

**What it does well:**
- Runs behavioral model computation for all users
- Memory maintenance: decay unreferenced facts, prune low-confidence facts, consolidate entities
- Scheduled at 3:00 AM UTC via APScheduler

**What's missing:**

1. **No feedback aggregation step**. Nightly reflection computes behaviors (active hours, message length preference, response speed, language register) but doesn't compute feedback-derived metrics (preferred categories, optimal send times, format preferences, category suppression list).

2. **No trend computation**. Engagement rate is a snapshot (last 30 days). Nightly reflection should compute: engagement rate this week vs last week vs 2 weeks ago. This gives the LLM trend direction.

3. **No feedback → behavior cross-analysis**. A user's response speed to proactive messages (feedback data) should inform their `response_speed` behavior model. Currently these are separate systems.

### `agent/nodes/memory.py` — Reactive feedback capture

**What it does well:**
- Calls `check_and_update_feedback(user_id)` on every user message — this is the primary mechanism for marking proactive messages as "engaged"
- Extracts memory facts from the conversation (which could include reactions to proactive messages)

**What's missing:**

1. **No sentiment analysis on the reply**. When a user replies to a proactive message, the content of the reply carries signal: "thanks!" is positive, "ok" is neutral, "stop sending me these" is very negative. Currently, any reply = "engaged."

2. **No proactive-specific memory extraction**. If a user says "those deadline reminders are really helpful" or "I already know my schedule, you don't need to tell me," these are meta-feedback about Donna's behavior. They should be stored as preferences and fed back into the proactive system.

---

## 3. The Feedback Loop Architecture

### Current Loop (Incomplete)

```
Send message
    ↓
Record in ProactiveFeedback (outcome: pending)
    ↓
Wait for user to message (any message)
    ↓
Mark as "engaged" (within 60 min) or "ignored" (after 180 min)
    ↓
Compute engagement_by_category (on next proactive cycle)
    ↓
Inject into LLM prompt as text
    ↓
Hope the LLM adjusts (stateless — no guarantee)
```

### Target Loop (Closed)

```
Send message (with format, template, wa_message_id)
    ↓
Record in ProactiveFeedback
    ↓
┌─ Delivery webhook:    mark delivered / read / failed
├─ User replies:        classify sentiment (positive / neutral / negative)
├─ Button tap:          record which button + context payload
├─ Timeout (180 min):   mark as ignored (only if delivered)
└─ Timeout (undelivered): mark as "undelivered" (not feedback)
    ↓
Nightly reflection: compute derived metrics
    ├─ Category preference scores (engagement × recency decay)
    ├─ Optimal send-time windows (hour-of-day engagement analysis)
    ├─ Format preference (button vs text vs list engagement)
    ├─ Signal-type engagement rates
    ├─ Trend direction per category (rising / stable / falling)
    └─ Category suppression list (0% engagement, 5+ attempts)
    ↓
Store as UserBehavior rows (persistent, trust-weighted)
    ↓
Feed back into:
    ├─ Layer 2 (prefilter): skip suppressed categories
    ├─ Layer 3 (context):   inject preference scores, trends, suppression list
    ├─ Layer 4 (generation): category weighting, format hints, time-of-day guidance
    └─ Layer 5 (delivery):  format selection, send-time optimization
```

---

## 4. Signal Capture: What Counts as Feedback

### Explicit Signals

| Signal | Where Captured | Current Status | Outcome |
|--------|---------------|----------------|---------|
| User replies within 60 min | `memory_writer` → `check_and_update_feedback()` | ✅ Working | engaged |
| User taps a button | `webhook.py` → button reply handler | ⚠️ Partially (detected but not stored as feedback) | button_click |
| User replies after 60 min | `check_and_update_feedback()` | ❌ Missed — already marked ignored | late_engage |
| No reply after 180 min | `check_and_update_feedback()` | ✅ Working | ignored |

### Implicit Signals (NEW)

| Signal | Where Captured | What It Means |
|--------|---------------|---------------|
| WhatsApp `delivered` status | Webhook status handler | Message reached phone |
| WhatsApp `read` status | Webhook status handler | User opened chat (strong signal even without reply) |
| WhatsApp `failed` status | Webhook status handler | Message never delivered (NOT a feedback signal) |
| Reply sentiment: positive | Memory writer + sentiment classifier | User liked the message |
| Reply sentiment: negative | Memory writer + sentiment classifier | User disliked the message — suppress category |
| Reply references proactive content | Memory writer + intent classifier | User engaged with the specific topic |
| Reply is about Donna's behavior | Memory writer + meta-feedback detector | User is giving explicit feedback about preferences |

### Meta-Feedback Detection (NEW)

When a user says something about Donna's proactive behavior itself, that's the highest-signal feedback:

```
"those reminders are really helpful"     → boost deadline_warning category
"stop texting me about my schedule"      → suppress schedule_info category
"you always text at the wrong time"      → time-of-day preference adjustment
"I prefer shorter messages"              → message_length_pref override
"can you text me earlier in the morning" → wake-time adjustment
"the buttons are useful"                 → format preference: buttons
```

These should be detected by the intent classifier (or a dedicated meta-feedback classifier) and stored as high-confidence `UserBehavior` entries that immediately override computed preferences.

---

## 5. Outcome Classification

### Current: Binary

```
replied within 60 min  → "engaged"
no reply after 180 min → "ignored"
button tap             → "button_click"
```

### Target: Granular

```python
OUTCOME_HIERARCHY = {
    # Positive (user found value)
    "positive_reply":  1.0,   # Replied with positive sentiment
    "button_click":    0.9,   # Tapped an interactive button
    "task_completed":  0.9,   # Completed the task Donna mentioned
    "neutral_reply":   0.7,   # Replied but neutral sentiment
    "read":            0.3,   # Read receipt but no reply (still signal)

    # Neutral (ambiguous)
    "late_engage":     0.4,   # Replied after 60 min but before 180 min
    "delivered_only":  0.1,   # Delivered but not read (phone in pocket)

    # Negative (user found no value or was annoyed)
    "ignored":         0.0,   # Read but no reply after 180 min
    "negative_reply": -0.5,   # Replied with negative sentiment
    "explicit_stop":  -1.0,   # User explicitly asked to stop

    # Non-feedback (don't count)
    "undelivered":     None,  # Never reached phone — not a signal
    "pending":         None,  # Still waiting
}
```

Each outcome has a **feedback score** that feeds into the preference learning system. Positive scores reinforce; negative scores suppress; `None` values are excluded from calculations.

### Sentiment Classification

When the user replies to a proactive message, classify the reply's sentiment. This doesn't need a heavy LLM call — a lightweight classifier is sufficient:

**Positive indicators**: "thanks", "helpful", "got it", "perfect", "nice", "good to know", emoji reactions (👍, ❤️, 🙏)

**Negative indicators**: "stop", "don't", "annoying", "not helpful", "I know", "leave me alone", "too many messages"

**Neutral**: everything else — "ok", "sure", direct task-related responses

```python
def classify_reply_sentiment(reply_text: str) -> str:
    """Quick sentiment classification of reply to proactive message.

    Returns: "positive" | "negative" | "neutral"
    """
```

For V1, this can be keyword-based. For V2, pipe through GPT-4o-mini with a 5-line prompt.

---

## 6. Per-User Learning: What Donna Adapts

### 6.1 Category Preferences

**What it is**: A per-user score for each proactive category reflecting how much the user values that type of message.

**How it's computed**:

```python
def compute_category_preferences(feedback_entries: list[ProactiveFeedback]) -> dict:
    """Compute preference score per category with recency decay.

    Returns: {"deadline_warning": 0.85, "wellbeing": 0.12, ...}
    """
    # Weight recent feedback more heavily
    # feedback_score × recency_weight (exponential decay, half-life 14 days)
    # Normalize to [0, 1] range
    # Require minimum 3 data points per category before outputting a score
```

**How it's used**:
- Injected into `candidates.py` system prompt as structured data (not just engagement rates)
- Categories with score < 0.15 are flagged for suppression
- Categories with score > 0.7 get a score bonus in `rules.py`

### 6.2 Optimal Send Windows

**What it is**: Per-user hour-of-day engagement profile.

**How it's computed**:

```python
def compute_send_time_preferences(feedback_entries: list[ProactiveFeedback]) -> dict:
    """Analyze engagement by hour-of-day (in user's timezone).

    Returns: {
        "peak_engagement_hours": [9, 10, 20, 21],
        "avoid_hours": [14, 15],  # consistently ignored
        "hourly_rates": {8: 0.6, 9: 0.8, ...},
    }
    """
```

**How it's used**:
- Layer 5 `send_time_optimization`: prefer sending during peak engagement hours
- Layer 2 `prefilter`: penalize signals that would result in sends during avoid_hours (unless urgent)
- Layer 4 `voice.py`: time-of-day tone calibration (already exists, but now backed by data)

### 6.3 Format Preferences

**What it is**: Per-user engagement rates by WhatsApp message format.

**How it's computed**:

```python
def compute_format_preferences(feedback_entries: list[ProactiveFeedback]) -> dict:
    """Analyze engagement by message format.

    Returns: {
        "preferred_format": "button",
        "format_rates": {"button": 0.85, "text": 0.45, "list": 0.6, "template": 0.3},
    }
    """
```

**How it's used**:
- Layer 5 `_select_message_format()`: bias toward preferred format when multiple formats are valid
- Layer 4 `candidates.py`: tell the LLM to use `button_prompt` action type more often if user prefers buttons

### 6.4 Response Speed Profile

**What it is**: How quickly the user typically responds to proactive messages, by category and time-of-day.

**Currently partially implemented**: `response_latency_seconds` is stored. `get_feedback_summary()` computes an overall average. But no breakdown by category or time.

**Target**:

```python
def compute_response_speed_profile(feedback_entries: list[ProactiveFeedback]) -> dict:
    """Break down response speed by category and time bucket.

    Returns: {
        "overall_median_minutes": 12.5,
        "by_category": {"deadline_warning": 4.2, "wellbeing": 45.0},
        "by_time_bucket": {"morning": 8.0, "afternoon": 15.0, "evening": 5.0},
    }
    """
```

**How it's used**:
- Adjust the `ENGAGEMENT_WINDOW_MINUTES` per user — a user who typically replies in 5 minutes and hasn't replied in 30 is "ignored." A user who typically replies in 45 minutes should get a longer window.
- Inform urgency scoring — if this user responds slowly to everything, a 12-minute response latency doesn't mean low urgency.

### 6.5 Category Suppression & Re-introduction

**What it is**: Mechanism to stop sending message categories that consistently get ignored or trigger negative feedback.

**Suppression rules**:
- If a category has **≥5 sends and 0% engagement** in the last 14 days → suppress
- If a category has **≥3 negative replies** in the last 14 days → suppress immediately
- If the user **explicitly asks** to stop a category → suppress immediately + mark as `explicit_stop`

**Re-introduction rules**:
- After 21 days of suppression, send ONE probationary message in that category (require score ≥ 8.0)
- If the probationary message gets engagement → lift suppression, reset counters
- If ignored → extend suppression for another 21 days
- `explicit_stop` categories are NEVER automatically re-introduced — only lifted if the user explicitly asks

**Storage**: `UserBehavior` with `behavior_key = "category_suppression"`:

```json
{
    "suppressed": {
        "wellbeing": {"since": "2026-01-15", "reason": "low_engagement", "probation_at": "2026-02-05"},
        "social": {"since": "2026-01-20", "reason": "explicit_stop", "probation_at": null}
    }
}
```

---

## 7. Feedback → Layer Integration

### Layer 2 (Decision Engine / Prefilter)

**What feedback provides**: Category suppression list, signal-type engagement rates.

**Integration point**: `prefilter.py` already loads `signal_sensitivity` from `UserBehavior` and increases `min_urgency` for ignored signal types. Extend this with feedback-derived data:

```python
# In prefilter_signals():
# Load category suppression list
suppressions = behavior_value.get("suppressed", {})
for s in signals:
    mapped_category = SIGNAL_TO_CATEGORY.get(s.type.value)
    if mapped_category in suppressions:
        suppression = suppressions[mapped_category]
        if suppression["reason"] == "explicit_stop":
            # Hard block — user asked to stop
            continue
        if _is_probation_due(suppression):
            # Allow one probationary message through
            pass
        else:
            # Suppress — don't even pass to LLM
            continue
```

### Layer 3 (User Model / Context)

**What feedback provides**: Category preferences, send-time preferences, format preferences, trend data.

**Integration point**: `context.py` already loads `feedback_summary`. Extend with computed preference data:

```python
# In build_context():
context["category_preferences"] = snapshot.get("behaviors", {}).get("category_preferences", {})
context["send_time_preferences"] = snapshot.get("behaviors", {}).get("send_time_preferences", {})
context["format_preferences"] = snapshot.get("behaviors", {}).get("format_preferences", {})
context["engagement_trends"] = snapshot.get("behaviors", {}).get("engagement_trends", {})
```

### Layer 4 (Message Generation)

**What feedback provides**: Category weighting for the LLM, format hints, trend direction.

**Integration point**: `candidates.py` `_build_dynamic_sections()` already injects feedback data. Extend:

```python
# In _build_dynamic_sections():
# Add trend direction
trends = context.get("engagement_trends", {})
if trends:
    trend_lines = []
    for cat, trend in trends.items():
        direction = trend.get("direction", "stable")  # "rising", "stable", "falling"
        trend_lines.append(f"  - {cat}: {trend.get('current_rate', 0):.0%} ({direction})")
    parts.append(
        "\n\nENGAGEMENT TRENDS (vs. 2 weeks ago):\n" + "\n".join(trend_lines) + "\n"
        "Rising categories: lean into them. Falling categories: reduce frequency or change approach."
    )

# Add format preference hint
fmt_pref = context.get("format_preferences", {})
preferred = fmt_pref.get("preferred_format")
if preferred == "button":
    parts.append(
        "\n\nFORMAT HINT: This user engages more with button messages. "
        "Use action_type 'button_prompt' when the message naturally invites a choice."
    )
```

### Layer 5 (Delivery)

**What feedback provides**: Format preferences, send-time windows, per-user engagement window duration.

**Integration point**: `sender.py` format selection and send-time optimization.

```python
# In _select_message_format():
# If format preferences show strong button preference AND message works as button
fmt_pref = context.get("format_preferences", {})
if fmt_pref.get("preferred_format") == "button" and _can_be_button(candidate):
    return "button"
# ... existing logic as fallback
```

---

## 8. Nightly Reflection Integration

### Current Reflection (`donna/reflection.py`)

Runs at 3:00 AM UTC. Computes: active_hours, message_length_pref, response_speed, language_register. Runs memory maintenance: decay, prune, consolidate.

### Target: Add Feedback Aggregation Step

Add a new batch of computations to `run_reflection()`:

```python
async def run_reflection(user_id: str) -> None:
    # ... existing behavior computation ...

    # NEW: Feedback-derived metrics
    try:
        await _compute_feedback_metrics(user_id)
    except Exception:
        logger.exception("Feedback metric computation failed for %s", user_id)

    # ... existing memory maintenance ...
```

### Feedback Metrics to Compute Nightly

1. **`category_preferences`**: Per-category engagement score with 14-day half-life decay.

2. **`engagement_trends`**: Compare this week's engagement rate vs. last week and 2 weeks ago, per category. Store trend direction: `rising` (≥10% increase), `falling` (≥10% decrease), `stable`.

3. **`send_time_preferences`**: Hour-of-day engagement rates in the user's timezone. Identify peak hours (top 3) and avoid hours (bottom 3 with ≥3 data points).

4. **`format_preferences`**: Engagement rate by message format (`text`, `button`, `list`, `cta_url`, `template`). Minimum 3 data points per format before computing.

5. **`category_suppression`**: Check if any category should be suppressed (≥5 sends, 0% engagement, 14 days) or if a suppression probation is due.

6. **`adaptive_engagement_window`**: Per-user engagement window duration. If median response time is 8 minutes, set window to `max(30, median × 3)` = 30 minutes. If median is 45 minutes, set window to 135 minutes. Cap at 180 minutes.

7. **`proactive_engagement_rate`** on `User` model: Update the cached aggregate rate for quick access in prefilter.

### Computation Schedule

All feedback metrics use the `BEHAVIOR_COMPUTERS` pattern from `donna/brain/behaviors.py`, so they slot into the existing reflection loop:

```python
# In donna/brain/behaviors.py, add:
FEEDBACK_COMPUTERS = {
    "category_preferences": compute_category_preferences,
    "engagement_trends": compute_engagement_trends,
    "send_time_preferences": compute_send_time_preferences,
    "format_preferences": compute_format_preferences,
    "category_suppression": compute_category_suppression,
    "adaptive_engagement_window": compute_adaptive_engagement_window,
}
```

---

## 9. Anti-Patterns & Safety Rails

### Anti-Pattern 1: Echo Chamber

**Risk**: If Donna only sends message types the user historically engaged with, she'll converge to a narrow set of categories. A student who only replied to deadline reminders will never discover that Donna can help with scheduling or wellbeing.

**Mitigation**: Exploration budget. 10% of proactive messages should be from non-preferred categories (with higher score threshold). This is the classic explore/exploit tradeoff.

```python
# In rules.py score_and_filter():
if random.random() < 0.1:  # 10% exploration
    # Allow one candidate from a non-preferred category
    # But still require composite score ≥ 6.0 (higher than usual threshold)
    pass
```

### Anti-Pattern 2: Negative Spiral

**Risk**: A user ignores 3 messages (they were busy with exams). Engagement rate drops. Donna sends fewer messages. User doesn't notice Donna because messages are rare. Engagement rate drops further. Donna goes silent.

**Mitigation**: Minimum message floor. Even at the lowest engagement rate, Donna should send at least 1 message per week (if there's something genuinely urgent to say). The floor is engagement-adjusted but never zero.

```python
# In nightly reflection:
if days_since_last_proactive > 7 and has_urgent_signal:
    # Override suppression for genuinely urgent signals
    pass
```

### Anti-Pattern 3: Stale Preferences

**Risk**: A user's preferences computed in September (start of semester: high engagement with schedule messages) persist into December (end of semester: user only cares about exam reminders). The feedback system is too slow to adapt.

**Mitigation**: 14-day half-life decay on all feedback signals. This means September preferences contribute only 0.5^(90/14) ≈ 1% by December — effectively expired. The system naturally adapts as new data arrives.

### Anti-Pattern 4: Cold Start

**Risk**: A new user has zero feedback data. The system can't compute preferences, so it falls back to defaults. But defaults might not match this specific user, leading to early negative experiences.

**Mitigation**: Trust ramp (Layer 2) already handles this — new users get conservative messaging. Additionally, use the user's reactive behavior (how they respond to Donna when they message first) to bootstrap preferences:

- User writes in short messages → preference for short proactive messages
- User is active at 11 PM → evening messages are ok
- User asks about deadlines frequently → deadline reminders will be valued

This reactive-to-proactive bootstrapping bridges the cold start gap.

### Anti-Pattern 5: Gaming/Overfitting

**Risk**: A user casually replied "ok" to a wellbeing check-in once (0.7 feedback score). The system massively boosts wellbeing messages. User gets annoyed.

**Mitigation**: Require minimum sample size before adjusting. The current design requires ≥3 data points per category/format before computing preferences. This prevents single-event overfitting. Combined with recency decay, this ensures stable adaptation.

---

## 10. Implementation Plan

### Phase 1: Enhanced Outcome Classification (Week 1)

**Goal**: Move from binary (engaged/ignored) to granular outcomes.

1. Add `delivery_status` field to `ProactiveFeedback` ("sent", "delivered", "read", "failed")
2. Add `reply_sentiment` field ("positive", "neutral", "negative", None)
3. Create `classify_reply_sentiment()` — keyword-based V1
4. Update `check_and_update_feedback()`:
   - Classify reply sentiment before marking as engaged
   - Differentiate "read but ignored" from "never delivered" using delivery status
   - Add "late_engage" for replies between 60-180 minutes
5. Update `memory_writer` to pass reply text to sentiment classifier when marking feedback

**Files touched**: `donna/brain/feedback.py`, `agent/nodes/memory.py`, `db/models.py`

### Phase 2: Meta-Feedback Detection (Week 1-2)

**Goal**: Detect and store when users give explicit feedback about Donna's behavior.

1. Add meta-feedback patterns to `intent_classifier` or create `detect_meta_feedback()`:
   - "stop sending me X" → suppress category X
   - "the reminders are helpful" → boost relevant category
   - "text me earlier" → time preference adjustment
2. Store meta-feedback as high-confidence `UserBehavior` entries
3. Meta-feedback overrides computed preferences immediately (no waiting for nightly reflection)

**Files touched**: `agent/nodes/classifier.py` or new `donna/brain/meta_feedback.py`, `agent/nodes/memory.py`

### Phase 3: Nightly Feedback Aggregation (Week 2)

**Goal**: Compute preference metrics from accumulated feedback data.

1. Create `donna/brain/feedback_metrics.py` with computation functions:
   - `compute_category_preferences()`
   - `compute_engagement_trends()`
   - `compute_send_time_preferences()`
   - `compute_format_preferences()`
   - `compute_adaptive_engagement_window()`
2. Register as `FEEDBACK_COMPUTERS` in `donna/brain/behaviors.py`
3. Add to `run_reflection()` in `donna/reflection.py`
4. Verify metrics are loaded in `get_user_snapshot()` and passed through `build_context()`

**Files touched**: new `donna/brain/feedback_metrics.py`, `donna/brain/behaviors.py`, `donna/reflection.py`

### Phase 4: Category Suppression System (Week 2-3)

**Goal**: Automatically suppress message categories with persistent zero engagement.

1. Add `compute_category_suppression()` to feedback metrics
2. Update `prefilter.py` to load and apply suppression list
3. Implement probationary re-introduction (21-day cooldown, single high-score attempt)
4. Handle `explicit_stop` separately — never auto-reintroduce
5. Add logging for suppression events (for debugging and user support)

**Files touched**: `donna/brain/feedback_metrics.py`, `donna/brain/prefilter.py`

### Phase 5: Feedback → Generation Integration (Week 3)

**Goal**: Category preferences, trends, and format hints flow into the LLM prompt.

1. Extend `_build_dynamic_sections()` in `candidates.py` with trend data and format hints
2. Add category preference scores to the context (not just raw engagement rates)
3. Update the system prompt to explicitly reference preference scores: "Categories scored below 0.2 should be avoided unless urgency ≥ 8"
4. Add exploration budget (10% of cycles allow non-preferred categories)

**Files touched**: `donna/brain/candidates.py`, `donna/brain/context.py`

### Phase 6: Feedback → Delivery Integration (Week 3-4)

**Goal**: Format preferences and send-time windows influence delivery decisions.

1. Update `_select_message_format()` in `sender.py` to bias toward preferred format
2. Update send-time optimization (from Layer 5) to use `send_time_preferences`
3. Update engagement window duration per user (from `adaptive_engagement_window`)

**Files touched**: `donna/brain/sender.py`, `donna/brain/feedback.py`

### Phase 7: Dashboard & Monitoring (Week 4)

**Goal**: Visibility into feedback loop health.

1. Add `/api/admin/feedback/{user_id}` endpoint returning:
   - Category preference scores
   - Suppressed categories
   - Engagement trends
   - Format preferences
   - Recent feedback entries with outcomes
2. Add aggregate health metrics:
   - Global engagement rate across all users
   - Category suppression frequency
   - Negative feedback rate
   - Exploration vs exploitation ratio

**Files touched**: new `api/admin.py` or extend existing admin endpoints

---

## Appendix A: Feedback Data Model Changes

### `ProactiveFeedback` — Enhanced

New columns:
- `wa_message_id` (String, nullable) — WhatsApp message ID for status correlation
- `format_used` (String, nullable) — "text" | "button" | "list" | "cta_url" | "template"
- `template_name` (String, nullable) — which template was used
- `delivery_status` (String, default "unknown") — "sent" | "delivered" | "read" | "failed"
- `delivery_failed_reason` (String, nullable) — WhatsApp error code
- `reply_sentiment` (String, nullable) — "positive" | "neutral" | "negative"
- `feedback_score` (Float, nullable) — computed outcome score from `OUTCOME_HIERARCHY`

### `UserBehavior` — New Keys

| `behavior_key` | `value` shape | Computed by |
|----------------|---------------|-------------|
| `category_preferences` | `{"deadline_warning": 0.85, "wellbeing": 0.12, ...}` | `compute_category_preferences()` |
| `engagement_trends` | `{"deadline_warning": {"current_rate": 0.8, "direction": "rising"}, ...}` | `compute_engagement_trends()` |
| `send_time_preferences` | `{"peak_hours": [9, 20], "avoid_hours": [14], "hourly_rates": {...}}` | `compute_send_time_preferences()` |
| `format_preferences` | `{"preferred_format": "button", "format_rates": {...}}` | `compute_format_preferences()` |
| `category_suppression` | `{"suppressed": {"wellbeing": {"since": "...", "reason": "...", ...}}}` | `compute_category_suppression()` |
| `adaptive_engagement_window` | `{"window_minutes": 45, "median_response_minutes": 12}` | `compute_adaptive_engagement_window()` |

---

## Appendix B: Feedback Score Computation

The per-category preference score uses exponential recency decay:

```
For each feedback entry in the last 60 days:
    days_ago = (now - entry.sent_at).days
    recency_weight = 0.5 ^ (days_ago / 14)   # 14-day half-life
    weighted_score = entry.feedback_score × recency_weight

    category_scores[entry.category].append(weighted_score)

For each category:
    if len(scores) < 3:
        preference = None  # insufficient data
    else:
        preference = mean(scores)  # normalized to [-0.5, 1.0] range
        preference = max(0, preference)  # clamp negatives to 0 for preference score
```

This means:
- A message sent today with positive engagement contributes 1.0 × 1.0 = 1.0
- The same message from 14 days ago contributes 1.0 × 0.5 = 0.5
- The same message from 28 days ago contributes 1.0 × 0.25 = 0.25
- By 56 days, it contributes only 0.0625 — nearly irrelevant

This naturally handles semester transitions: September patterns fade by November as new December patterns dominate.
