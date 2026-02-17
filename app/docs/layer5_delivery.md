# Layer 5: Delivery — Architecture & Implementation Plan

> **What Layer 5 does**: Takes a composed message and gets it to the student's phone through the right channel, in the right format, at the right time — handling WhatsApp's service window constraints, delivery confirmation, retry logic, and send-time optimization.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Current State Audit](#2-current-state-audit)
3. [The Delivery Pipeline](#3-the-delivery-pipeline)
4. [Service Window Management](#4-service-window-management)
5. [Format Routing](#5-format-routing)
6. [Send-Time Optimization](#6-send-time-optimization)
7. [Delivery Confirmation & Retry](#7-delivery-confirmation--retry)
8. [Message Persistence](#8-message-persistence)
9. [Error Taxonomy & Handling](#9-error-taxonomy--handling)
10. [Implementation Plan](#10-implementation-plan)

---

## 1. The Problem

Delivery looks deceptively simple — "just POST to the WhatsApp API." But this layer sits at the boundary between Donna's brain and the real world, and that boundary is full of constraints:

- **WhatsApp's 24-hour service window**: Outside this window, you can ONLY send pre-approved template messages. Inside, you get freeform text + interactive formats. Misjudging the window = API rejection = silent failure.
- **Template parameter limits**: Each template slot is capped at 1024 characters. Parameters must match the registered template exactly. One wrong slot count = `#132000 PARAMETER_MISSING`.
- **Rate limits**: WhatsApp Business API has per-phone-number throughput limits (80 msgs/sec at Tier 1, scaling with quality rating). Bulk sends for all users could hit these.
- **Silent failures**: The current code doesn't check `resp.json()` for error payloads — a 200 response can still contain a WhatsApp error. Messages can be "sent" but never delivered (phone off, number changed, user blocked).
- **Format fragility**: WhatsApp interactive messages (buttons, lists, CTA) have strict structural requirements — wrong `id` length, too many rows, missing fields = hard rejection.
- **No retry**: If a send fails, it's gone. No queue, no retry, no fallback to simpler format.

The research is clear: delivery reliability directly impacts user trust. A missed deadline reminder because of a template parameter error is worse than never having the proactive system at all — the student trusted Donna to tell them, and Donna silently failed.

---

## 2. Current State Audit

### `donna/brain/sender.py` — The delivery orchestrator

This is the strongest piece. Recent modifications (based on Layer 4 recommendations) have significantly improved it.

**What it does well:**
- `_is_window_open()` correctly checks for user messages in the last 24h
- `_select_message_format()` is deterministic — routes based on `action_type`, `category`, and content shape
- Template routing uses `CATEGORY_TEMPLATE_MAP` to match candidate categories to registered Meta templates
- `fill_template_params()` (from `template_filler.py`) uses a lightweight LLM call instead of fragile string splitting
- `validate_message()` (from `validators.py`) catches banned phrases, leakage, bad markdown, length violations
- `validate_template_params()` truncates to 1024-char slot limit
- `_build_briefing_sections()` correctly parses multi-line briefings into WhatsApp list format
- Persists sent messages as `ChatMessage` with `is_proactive=True`
- Records to `ProactiveFeedback` for the feedback loop

**What's missing:**

1. **No delivery confirmation**. The code calls `send_whatsapp_*()` and assumes success based on no exception. But WhatsApp returns `{"messages": [{"id": "wamid.xxx"}]}` on success and `{"error": {"code": 131047, ...}}` on failure — and BOTH come back as HTTP 200 in some cases. The current `whatsapp.py` checks `resp.status_code != 200` and logs, but doesn't propagate the error object back to `sender.py`.

2. **No retry logic**. If `send_whatsapp_buttons()` fails because the button `id` is too long or missing, the message is lost. No fallback to plain text. No retry queue.

3. **No send-time optimization**. Messages are sent immediately when the 5-minute scheduler fires. If the scheduler runs at 2:03 AM and the user's quiet hours end at 8:00 AM, prefilter blocks it — but the message is discarded entirely instead of being queued for 8:00 AM.

4. **Window check is binary**. `_is_window_open()` returns True/False, but doesn't tell the caller HOW MUCH time is left. If the window closes in 2 minutes, sending a freeform message is risky — it might arrive after the window closes, causing delivery failure on WhatsApp's side.

5. **No delivery status tracking**. WhatsApp sends delivery status webhooks (`delivered`, `read`, `failed`) back to our `/webhook` endpoint. These are currently ignored — there's no handler for status updates. This is free data that tells us exactly whether the message reached the user's phone.

6. **`_build_briefing_sections()` has structural issues**:
   - Row `title` is truncated at 24 chars but WhatsApp allows 24 — if the 24th char is mid-word, it looks broken
   - Row `description` slices `line[24:72]` but this is just a substring of the same line, not a meaningful description
   - No `id` prefix prevents collision if the same briefing runs twice in a day

7. **Template button payloads are static**. `TEMPLATES_WITH_BUTTONS` maps template names to fixed payloads (`["got_it", "remind_later"]`), but these payloads don't include any context about WHICH deadline or WHICH task. When the user taps "remind_later" on a template, the webhook receives `payload: "remind_later"` with no way to know what to remind about.

### `tools/whatsapp.py` — The transport layer

**What it does well:**
- Clean, focused functions — one per WhatsApp message type
- Correct API payloads matching Meta's documentation
- Uses `httpx.AsyncClient` for non-blocking HTTP
- `download_media()` properly chains the media URL lookup → download

**What's missing:**

1. **No response parsing**. Every function returns `resp.json()` raw. The caller has no structured way to know if the message was accepted. Need a `WhatsAppResponse` dataclass with `success`, `message_id`, `error_code`, `error_detail`.

2. **New client per request**. Each call creates `async with httpx.AsyncClient()`. This means no connection pooling, no keep-alive. For the scheduler running across 50+ users, this creates unnecessary TCP overhead. Should use a module-level client or a connection pool.

3. **No timeout configuration**. `httpx` defaults to 5s connect + 5s read. WhatsApp API can be slow under load — need explicit timeouts.

4. **Template `button` component indexing**. The current code uses `"index": str(i)` but WhatsApp expects `"index": i` (integer, not string) in some API versions. This is a potential silent failure depending on the API version.

5. **Missing `send_whatsapp_image()`** and **`send_whatsapp_document()`**. Donna doesn't currently send media, but Layer 5 should plan for it — exam schedule screenshots, PDF summaries, etc.

### `donna/brain/template_filler.py` — Parameter generation

**What it does well:**
- Uses GPT-4o-mini (fast, cheap) for parameter filling
- Single-slot templates skip the LLM entirely — just truncate the message
- Fallback `_naive_split()` handles LLM failures gracefully
- Slot count auto-computed from template text

**What's missing:**

1. **No template registry validation**. `TEMPLATE_TEXTS` is hardcoded but there's no check that these match what's actually registered in Meta Business Manager. A drift between code and Meta config = hard failures.

2. **No caching**. If the same candidate generates template params and the send fails + retries, it calls the LLM again. Should cache params for the duration of the send attempt.

### `donna/brain/validators.py` — Pre-send validation

**What it does well:**
- Comprehensive banned-phrase list matching Donna's voice rules
- System prompt leakage detection (catches "as an AI", "language model", scoring artifacts)
- Bad markdown cleanup (WhatsApp doesn't render `##` headings or `[links](url)`)
- Signature removal (catches all "— Donna" variants)
- Returns warnings alongside cleaned message — doesn't silently mutate

**What's missing:**

1. **Banned phrases don't block sending**. They only add warnings. If the LLM says "Just checking in to see how you're doing", validation logs a warning but still sends it. The decision to block vs. warn should be configurable.

2. **No per-format validation**. Button messages need button IDs ≤ 256 chars and titles ≤ 20 chars. List messages need row IDs ≤ 200 chars and titles ≤ 24 chars. CTA URLs need valid HTTP(S). These format-specific constraints aren't validated.

3. **No emoji count enforcement**. Voice rules say "Maximum 1 per message. Usually 0." The validator doesn't count emojis.

---

## 3. The Delivery Pipeline

### Current Flow

```
candidate (from rules.py)
    │
    ├─ validate_message()         # Clean text, log warnings
    ├─ _is_window_open()          # Check 24h service window
    │
    ├─ IF window open:
    │   ├─ _select_message_format()  # text | button | list | cta_url
    │   └─ send_whatsapp_*()         # Call appropriate transport function
    │
    └─ IF window closed:
        ├─ CATEGORY_TEMPLATE_MAP     # Map category → template name
        ├─ fill_template_params()    # LLM fills {{1}} {{2}} slots
        ├─ validate_template_params()# Truncate to 1024
        └─ send_whatsapp_template()  # Send with button payloads if applicable
    │
    ├─ Persist as ChatMessage
    └─ record_proactive_send()    # Feedback tracking
```

### Target Flow

```
candidate (from rules.py)
    │
    ├─ validate_message()             # Clean text, log warnings
    ├─ validate_format_constraints()  # NEW: per-format structural checks
    ├─ _get_window_status()           # NEW: returns { open, minutes_remaining }
    │
    ├─ IF window open AND minutes_remaining > 5:
    │   ├─ _select_message_format()
    │   ├─ send_with_retry()          # NEW: retry with format fallback
    │   └─ parse_wa_response()        # NEW: structured success/failure
    │
    ├─ IF window open AND minutes_remaining ≤ 5:
    │   └─ Route to template path     # NEW: safety margin near window close
    │
    └─ IF window closed:
        ├─ CATEGORY_TEMPLATE_MAP
        ├─ fill_template_params()
        ├─ validate_template_params()
        ├─ send_with_retry()
        └─ parse_wa_response()
    │
    ├─ Store wa_message_id            # NEW: for delivery status tracking
    ├─ Persist as ChatMessage
    └─ record_proactive_send()
```

---

## 4. Service Window Management

### How WhatsApp's 24-Hour Window Works

When a user sends a message to a business, a 24-hour "conversation window" opens. Inside this window, the business can send any message type (text, interactive, media). Outside the window, ONLY pre-approved template messages are allowed.

**Key nuances the current code handles correctly:**
- `_is_window_open()` checks for the most recent `role="user"` message within 24 hours
- Returns boolean — simple, deterministic

**Key nuances the current code misses:**

1. **Window margin safety**. WhatsApp evaluates the window at message reception time, not send time. Network latency + queue processing means a message "sent" at 23:59:58 might be "received" at 00:00:01 and rejected. Need a 5-minute safety margin.

2. **Window extension**. Each user message RESETS the 24-hour clock. If the user replied to a proactive message 20 minutes ago, the window just extended. The current code checks for any user message in 24h, which is correct, but doesn't expose when the window actually closes.

3. **Session-based pricing**. Since June 2023, WhatsApp charges per "conversation session" (24h from first business message). Opening a template conversation is cheaper than a service conversation in some categories. Donna should prefer template messages when cost matters — but for a student assistant, reliability > cost.

### Target: `_get_window_status()`

```python
async def _get_window_status(user_id: str) -> dict:
    """Return window state with margin awareness.

    Returns:
        {
            "open": bool,
            "minutes_remaining": float | None,  # None if closed
            "safe_for_freeform": bool,           # False if < 5 min remaining
            "last_user_message_at": datetime | None,
        }
    """
```

The caller uses `safe_for_freeform` to decide: if True, send any format. If `open` but not `safe_for_freeform`, use template path to avoid rejection. If not `open`, template only.

---

## 5. Format Routing

### Current Format Selection Logic (`_select_message_format`)

```
action_type == "button_prompt"  →  button
category == "briefing" AND ≥3 newlines  →  list
category in (grade_alert, email_alert) AND data.link  →  cta_url
everything else  →  text
```

This is solid for the current categories. What's missing:

### Target Format Decision Tree

```
1. Does the candidate have action_type == "button_prompt"?
   → YES: Can we fit the buttons? (max 3, titles ≤ 20 chars)
     → YES: button
     → NO: text (with the question phrased as open-ended)

2. Does the candidate have a URL in data.link?
   → YES: cta_url (category doesn't matter)

3. Is the category "briefing" with ≥3 items?
   → YES: Can we build valid list sections? (rows ≤ 10, titles ≤ 24 chars)
     → YES: list
     → NO: text (formatted with line breaks + bold)

4. Is the message a yes/no question (detected from message text)?
   → YES: button (auto-generate "Yes" / "Not now" buttons)

5. Default: text
```

### Format-Specific Validation (NEW)

Each format has WhatsApp API constraints that must be checked BEFORE sending:

**Button messages:**
- Max 3 buttons
- Button `id`: max 256 chars
- Button `title`: max 20 chars
- `body` text: max 1024 chars

**List messages:**
- Max 10 rows total across all sections
- Row `id`: max 200 chars
- Row `title`: max 24 chars
- Row `description`: max 72 chars
- `body` text: max 1024 chars
- `button` text (the "View" button): max 20 chars

**CTA URL messages:**
- `body` text: max 1024 chars
- `display_text`: max 20 chars
- `url`: must be valid HTTP(S), max 2000 chars

**Template messages:**
- Parameter values: max 1024 chars each
- Must match registered slot count exactly

```python
def validate_format_constraints(candidate: dict, fmt: str) -> tuple[bool, str | None]:
    """Check format-specific WhatsApp API constraints.

    Returns (is_valid, error_reason).
    If invalid, caller should fall back to simpler format.
    """
```

---

## 6. Send-Time Optimization

### Current Behavior

The scheduler fires every 5 minutes. If prefilter says "quiet hours" or "cooldown," the candidate is discarded. Next cycle, signals may have changed and the message is never regenerated.

This means: Donna thinks of a perfect deadline reminder at 2:03 AM, prefilter blocks it, and by the 8:00 AM cycle the signals have shifted. The message is lost.

### Target: Deferred Send Queue

Not every blocked message should be retried — if it was blocked for "daily cap reached," that's a hard stop. But if blocked for "quiet hours" or "near window close," the message should be queued.

**When to queue (not discard):**
- Quiet hours block → queue for `wake_time`
- Window closing soon → queue, will send as template when scheduler next fires
- Rate limit hit → queue for retry in 60 seconds

**When NOT to queue:**
- Daily cap reached → respect the cap, don't queue
- Cooldown active → the information may be stale by cooldown end
- Score too low → not worth sending later either

### Implementation: `DeferredSend` model

This is distinct from `DeferredInsight` (which stores borderline candidates for reactive use). `DeferredSend` stores approved messages that are temporarily blocked by delivery constraints.

```python
class DeferredSend(Base):
    __tablename__ = "deferred_sends"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    candidate_json = Column(JSON, nullable=False)   # Full candidate dict
    reason = Column(String, nullable=False)          # "quiet_hours" | "window_closing" | "rate_limit"
    scheduled_for = Column(DateTime, nullable=False)  # When to attempt delivery
    created_at = Column(DateTime, default=datetime.utcnow)
    attempted = Column(Boolean, default=False)
    expired = Column(Boolean, default=False)         # If the info becomes stale
```

A secondary scheduler job (every 1 minute) checks for due `DeferredSend` rows and attempts delivery. If the candidate's underlying signal is no longer relevant (deadline passed, event started), mark as expired instead.

### Staleness Check

Before sending a deferred message, verify the information is still accurate:
- Deadline reminders: Is the due date still in the future?
- Schedule info: Is the event still on the calendar?
- Email alerts: Has the user already read the email?

This is a lightweight check against signal data, not a full LLM re-evaluation.

---

## 7. Delivery Confirmation & Retry

### WhatsApp Delivery Statuses

WhatsApp sends status webhooks back to our `/webhook` endpoint:

```json
{
  "statuses": [
    {
      "id": "wamid.xxx",
      "status": "sent",        // accepted by WhatsApp servers
      "timestamp": "1234567890",
      "recipient_id": "65xxxxxxxx"
    }
  ]
}
```

Status progression: `sent` → `delivered` → `read` (or `failed` at any point).

**Currently**: The webhook handler in `api/webhook.py` processes incoming messages but ignores status updates entirely. This is free, high-signal data being thrown away.

### Target: Status Tracking

1. **Store `wa_message_id`** returned from successful sends in `ChatMessage` or `ProactiveFeedback`.

2. **Handle status webhooks** in `api/webhook.py`:
   - `sent`: Message accepted by WhatsApp infra. Expected.
   - `delivered`: Message reached user's phone. Log it.
   - `read`: User opened the chat. Stronger engagement signal than response.
   - `failed`: Delivery failed. Log error code + trigger alert if persistent.

3. **Enrich feedback data**: A `read` receipt without a reply is different from an `undelivered` message — the user saw it and chose not to engage, which is feedback. An `undelivered` message isn't feedback at all and shouldn't count as "ignored."

### Retry Strategy

```
Send attempt 1: preferred format (button, list, cta_url, text)
  ├─ Success → done
  └─ Failure:
      ├─ WhatsApp error 131047 (re-engagement required) → queue as template
      ├─ WhatsApp error 132000 (template param mismatch) → fix params, retry
      ├─ WhatsApp error 130472 (rate limit) → backoff 60s, retry
      ├─ WhatsApp error 131026 (not on WhatsApp) → log, skip user
      ├─ Format-specific error → fallback to plain text
      └─ Network error → retry with exponential backoff (max 3 attempts)
```

### Target: `send_with_retry()`

```python
async def send_with_retry(
    user_phone: str,
    candidate: dict,
    fmt: str,
    max_retries: int = 2,
) -> WhatsAppResult:
    """Send message with format fallback and retry logic.

    Tries preferred format first. On format-specific failure,
    falls back to plain text. On network failure, retries with backoff.

    Returns WhatsAppResult with success, wa_message_id, and error details.
    """
```

---

## 8. Message Persistence

### Current State

Sender persists every sent message as a `ChatMessage`:

```python
session.add(ChatMessage(
    id=message_id,
    user_id=user_id,
    role="assistant",
    content=message_text,
    is_proactive=True,
))
```

And records it in `ProactiveFeedback`:

```python
await record_proactive_send(user_id, message_id, candidate)
```

**What's good**: Both tables get the same `message_id`, creating a foreign-key-like link between the conversation record and the feedback record.

**What's missing:**

1. **No `wa_message_id` stored**. The WhatsApp message ID (returned by the API) is needed to correlate delivery status webhooks back to our records. Currently discarded.

2. **Format not recorded**. We don't know whether a message was sent as freeform text, button, list, CTA, or template. This is critical for the feedback loop — if buttons get 80% engagement but text gets 30%, we should prefer buttons.

3. **Template name not recorded** for template sends. If `donna_deadline_v2` has 90% engagement but `donna_check_in` has 20%, we need to know which template was used.

4. **No delivery status field**. `ChatMessage` has no way to record whether the message was delivered, read, or failed. This data comes from webhooks but has nowhere to go.

### Target: Enhanced Persistence

Add to `ProactiveFeedback`:
- `wa_message_id`: String — WhatsApp's message ID for status correlation
- `format_used`: String — "text" | "button" | "list" | "cta_url" | "template"
- `template_name`: String | None — which template was used (if template)
- `delivery_status`: String — "sent" | "delivered" | "read" | "failed"
- `delivery_failed_reason`: String | None — WhatsApp error code if failed

Add to `ChatMessage`:
- `wa_message_id`: String | None — for delivery status webhook correlation

---

## 9. Error Taxonomy & Handling

### WhatsApp API Error Codes (Common)

| Code | Meaning | Current Handling | Target Handling |
|------|---------|-----------------|-----------------|
| 131047 | Re-engagement required (window closed) | Silent failure (logged) | Re-route to template path |
| 132000 | Template parameter count mismatch | Silent failure | Fix params + retry |
| 132001 | Template not found/approved | Silent failure | Alert + skip |
| 130472 | Rate limit exceeded | Silent failure | Backoff + retry |
| 131026 | Recipient not on WhatsApp | Silent failure | Mark user, stop sending |
| 131051 | Unsupported message type | Silent failure | Fallback to text |
| 131053 | Media download failed | Silent failure | Retry or skip media |
| 368 | Temporarily blocked for policy | Silent failure | Cool off 24h |

### Current Error Handling

```python
# In sender.py — blanket exception catch
except Exception:
    logger.exception("Failed to send proactive message to %s", user.phone)
    return False
```

This catches everything but distinguishes nothing. A rate limit and a blocked account get the same treatment: log and move on.

### Target: Structured Error Response

```python
@dataclass
class WhatsAppResult:
    success: bool
    wa_message_id: str | None = None
    error_code: int | None = None
    error_message: str | None = None
    retryable: bool = False
    fallback_format: str | None = None  # suggest simpler format

def parse_wa_response(resp_json: dict) -> WhatsAppResult:
    """Parse WhatsApp API response into structured result."""
    if "messages" in resp_json:
        return WhatsAppResult(
            success=True,
            wa_message_id=resp_json["messages"][0]["id"],
        )
    error = resp_json.get("error", {})
    code = error.get("code", 0)
    return WhatsAppResult(
        success=False,
        error_code=code,
        error_message=error.get("message", ""),
        retryable=code in (130472, 131047),
        fallback_format="text" if code == 131051 else None,
    )
```

---

## 10. Implementation Plan

### Phase 1: Transport Reliability (Week 1)

**Goal**: Every send attempt gets a structured result. Silent failures eliminated.

1. Create `WhatsAppResult` dataclass in `tools/whatsapp.py`
2. Add `parse_wa_response()` that all send functions call before returning
3. Change all `send_whatsapp_*()` return types from `dict` to `WhatsAppResult`
4. Create module-level `httpx.AsyncClient` with connection pooling and explicit timeouts
5. Update `sender.py` to check `result.success` instead of assuming success
6. Add `wa_message_id` column to `ChatMessage` and `ProactiveFeedback`

**Files touched**: `tools/whatsapp.py`, `donna/brain/sender.py`, `db/models.py`

### Phase 2: Format Validation & Fallback (Week 1-2)

**Goal**: Format-specific constraints are checked before sending. Invalid formats fall back gracefully.

1. Add `validate_format_constraints()` to `validators.py`
2. Implement `send_with_retry()` in `sender.py` with format fallback chain: preferred → text
3. Fix `_build_briefing_sections()` — word-boundary truncation, meaningful descriptions, unique IDs
4. Add per-format validation for buttons (≤3, titles ≤20), lists (≤10 rows, titles ≤24), CTA (valid URL)

**Files touched**: `donna/brain/validators.py`, `donna/brain/sender.py`

### Phase 3: Window Safety Margin (Week 2)

**Goal**: No messages rejected due to window timing issues.

1. Replace `_is_window_open()` with `_get_window_status()` returning minutes remaining
2. Add 5-minute safety margin — route to template path when window is closing
3. Update `send_proactive_message()` to use the richer window status

**Files touched**: `donna/brain/sender.py`

### Phase 4: Delivery Status Tracking (Week 2-3)

**Goal**: WhatsApp delivery/read/failed statuses are captured and stored.

1. Add status webhook handler in `api/webhook.py` — parse `statuses` array
2. Add `delivery_status` and `delivery_failed_reason` columns to `ProactiveFeedback`
3. Add `format_used` and `template_name` columns to `ProactiveFeedback`
4. Correlate status updates to `ProactiveFeedback` rows via `wa_message_id`
5. Update feedback loop: `undelivered` messages don't count as "ignored"

**Files touched**: `api/webhook.py`, `db/models.py`, `donna/brain/feedback.py`

### Phase 5: Send-Time Optimization (Week 3)

**Goal**: Approved messages blocked by timing constraints are queued, not discarded.

1. Create `DeferredSend` model for temporarily-blocked approved messages
2. Update `prefilter.py` to return `block_reason` ("quiet_hours", "rate_limit") alongside `should_continue`
3. Update `donna/loop.py` to queue blocked-but-approved candidates as `DeferredSend`
4. Add scheduler job (every 1 minute) to process due `DeferredSend` rows
5. Add staleness check before sending deferred messages

**Files touched**: `db/models.py`, `donna/brain/prefilter.py`, `donna/loop.py`, `agent/scheduler.py`

### Phase 6: Contextual Template Buttons (Week 3-4)

**Goal**: Template button payloads carry context so taps can be routed correctly.

1. Update `TEMPLATES_WITH_BUTTONS` payloads to include candidate context: `"remind_later:task_id:abc123"`
2. Update webhook button reply handler to parse structured payloads
3. Implement "remind later" action: create a `DeferredSend` for +2 hours
4. Implement "done" action: mark the referenced task as completed

**Files touched**: `donna/brain/sender.py`, `api/webhook.py`, `tools/tasks.py`

### Phase 7: Connection Pooling & Rate Limiting (Week 4)

**Goal**: WhatsApp API calls are efficient and respect rate limits.

1. Create module-level `httpx.AsyncClient` with `limits=httpx.Limits(max_connections=20)`
2. Add async semaphore for per-phone-number rate limiting
3. Update scheduler to batch user processing with configurable concurrency
4. Add circuit breaker: if 5 consecutive sends fail for a user, pause for 1 hour

**Files touched**: `tools/whatsapp.py`, `agent/scheduler.py`

---

## Appendix: Key Metrics to Track

Once Layer 5 is implemented, these metrics become available:

| Metric | Source | What It Tells You |
|--------|--------|-------------------|
| Delivery rate | `ProactiveFeedback.delivery_status` | % of messages that reach the phone |
| Read rate | Status webhooks (`read`) | % of delivered messages that are opened |
| Template vs freeform ratio | `ProactiveFeedback.format_used` | How often we're inside vs outside the window |
| Format engagement by type | `format_used` × `outcome` | Which formats (button, list, text) drive engagement |
| Retry success rate | `send_with_retry` logs | How often fallback saves a message |
| Deferred send execution rate | `DeferredSend.attempted` | How often queued messages actually get sent |
| Window margin saves | Log when margin routing fires | How often the 5-min safety margin prevents failures |
| Template parameter errors | `parse_wa_response` error codes | How often the template filler produces bad params |
