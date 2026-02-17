# WhatsApp Business API — Message Template Reference

**For Donna Proactive Messaging System**
Meta Graph API v18.0+ | WhatsApp Cloud API

---

## 1. The 24-Hour Window Problem

WhatsApp enforces a strict messaging policy. After a user sends you a message, you have a **24-hour customer service window** during which you can send any message type (text, interactive buttons, lists, media). Outside this window, you can **ONLY send pre-approved template messages**.

This is architecturally critical for Donna. Proactive messages (deadline reminders, grade alerts, schedule nudges) often target users who haven't chatted recently. Without template messages, those proactive messages silently fail.

| Scenario | Window Status | What You Can Send |
|----------|---------------|-------------------|
| User messaged 2 hours ago | OPEN (within 24h) | Freeform text, buttons, lists, media |
| User messaged 30 hours ago | CLOSED (outside 24h) | Only approved template messages |
| User never messaged | NEVER OPENED | Only approved template messages |
| Donna sends proactive msg, user replies | RE-OPENED for 24h | Freeform text again |

**Key insight:** Template messages are the gateway. A well-crafted template that gets a reply re-opens the 24-hour window, allowing Donna to follow up with her full freeform personality.

---

## 2. Template Management API (CRUD)

Templates are created, read, updated, and deleted via the WhatsApp Business Management API. All requests require a System User access token with `whatsapp_business_management` permission.

### 2.1 Create a Template

**Endpoint:** `POST https://graph.facebook.com/v18.0/{WABA_ID}/message_templates`

**Required fields:**

- `name` (string) — lowercase alphanumeric + underscores only, max 512 chars
- `language` (string) — BCP 47 language code, e.g. `"en"` or `"en_US"`
- `category` (enum) — `UTILITY` | `MARKETING` | `AUTHENTICATION`
- `components` (array) — defines HEADER, BODY, FOOTER, and BUTTONS

**Example — Create a utility template (Python):**

```python
import httpx
from config import settings

WA_API = "https://graph.facebook.com/v18.0"

async def create_template(name: str, body_text: str, example_values: list[str]):
    """Create a utility template programmatically."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WA_API}/{settings.whatsapp_business_account_id}/message_templates",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json={
                "name": name,
                "language": "en",
                "category": "UTILITY",
                "components": [
                    {
                        "type": "BODY",
                        "text": body_text,
                        "example": {
                            "body_text": [example_values]
                        }
                    }
                ]
            },
        )
        return resp.json()
```

**Example — Create a template with header and buttons:**

```python
async def create_rich_template():
    payload = {
        "name": "deadline_reminder_v2",
        "language": "en",
        "category": "UTILITY",
        "components": [
            {
                "type": "HEADER",
                "format": "TEXT",
                "text": "Deadline Approaching"
            },
            {
                "type": "BODY",
                "text": "{{1}} is due {{2}}. {{3}}",
                "example": {
                    "body_text": [["CS2030S Lab 4", "tomorrow at 11:59 PM",
                                   "You usually start these the evening before."]]
                }
            },
            {
                "type": "FOOTER",
                "text": "Donna — your personal assistant"
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Got it"},
                    {"type": "QUICK_REPLY", "text": "Remind me later"}
                ]
            }
        ]
    }
    # ... POST to API
```

**Response (success):**

```json
{
  "id": "594425479261596",
  "status": "PENDING",
  "category": "UTILITY"
}
```

### 2.2 Check Template Status

**Endpoint:** `GET https://graph.facebook.com/v18.0/{WABA_ID}/message_templates`

```python
async def get_templates(status: str = None):
    """List all templates, optionally filtered by status."""
    params = {}
    if status:
        params["status"] = status  # APPROVED, PENDING, REJECTED
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{WA_API}/{settings.whatsapp_business_account_id}/message_templates",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            params=params,
        )
        return resp.json()
```

| Status | Meaning | Can Send? |
|--------|---------|-----------|
| APPROVED | Meta reviewed and approved | Yes |
| PENDING | Submitted, awaiting review (24-48h) | No |
| REJECTED | Failed review — check rejection reason | No |
| PAUSED | Meta paused due to quality issues | No |
| DISABLED | Permanently disabled | No |

### 2.3 Update a Template

**Endpoint:** `POST https://graph.facebook.com/v18.0/{TEMPLATE_ID}`

You can only edit templates in APPROVED, REJECTED, or PAUSED status. Edits are limited to **once per day, up to 10 times per month**. Editing an approved template re-triggers review.

### 2.4 Delete a Template

**Endpoint:** `DELETE https://graph.facebook.com/v18.0/{WABA_ID}/message_templates?name={name}`

Deletes all language versions of the named template. **Template names cannot be reused after deletion.**

---

## 3. Sending Template Messages

**Endpoint:** `POST https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages`

Same endpoint used for regular messages, but with `type: "template"` instead of `type: "text"`. Only APPROVED templates can be sent.

```python
async def send_template(to: str, template_name: str, params: list[str]):
    """Send a pre-approved template message."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WA_API}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": "en"},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": p}
                                for p in params
                            ]
                        }
                    ]
                }
            },
        )
        return resp.json()
```

**Template with quick reply buttons:**

```python
async def send_template_with_buttons(to, template_name, body_params, button_payloads):
    """Send template with quick reply buttons."""
    components = [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in body_params]
        }
    ]
    for i, payload in enumerate(button_payloads):
        components.append({
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(i),
            "parameters": [{"type": "payload", "payload": payload}]
        })
    # ... POST to messages endpoint with template type
```

### 3.1 Component Parameter Types

| Component | Parameter Type | Notes |
|-----------|---------------|-------|
| HEADER (text) | `{"type": "text", "text": "value"}` | Max 60 chars |
| HEADER (image) | `{"type": "image", "image": {"link": "url"}}` | Or use media ID |
| HEADER (document) | `{"type": "document", "document": {"link": "url"}}` | PDF, etc. |
| BODY | `{"type": "text", "text": "value"}` | Replaces {{1}}, {{2}}, etc. |
| BUTTON (quick_reply) | `{"type": "payload", "payload": "data"}` | Returned on tap |
| BUTTON (url) | `{"type": "text", "text": "suffix"}` | Appended to base URL |

---

## 4. Donna's Recommended Templates

These templates cover Donna's proactive messaging categories. Register once (via API or Business Manager), then reuse at runtime.

| Template Name | Category | Body Text | Variables |
|---------------|----------|-----------|-----------|
| `donna_deadline` | UTILITY | `Heads up — {{1}} is due {{2}}. {{3}}` | assignment, time, context |
| `donna_grade_alert` | UTILITY | `New grade posted for {{1}}: {{2}}. {{3}}` | course, score, context |
| `donna_schedule` | UTILITY | `Coming up: {{1}} at {{2}}. {{3}}` | event, time, note |
| `donna_daily_digest` | UTILITY | `Your day: {{1}}` | formatted schedule |
| `donna_study_nudge` | UTILITY | `You have free time {{1}}. {{2}}` | time window, suggestion |
| `donna_email_alert` | UTILITY | `{{1}} emails worth checking. {{2}}` | count, summary |
| `donna_general` | UTILITY | `{{1}}` | short message |
| `donna_check_in` | UTILITY | `{{1}} {{2}}` | greeting, context |

**Important constraints:**

- Template body max: 1,024 characters
- Each variable (`{{1}}`, `{{2}}`, etc.) replaces at send time
- You must provide example values when creating the template
- `donna_general` with a single `{{1}}` is risky — Meta may reject as too open-ended
- Quick reply buttons ("Got it", "Remind later") help re-open the 24h window
- Max 250 template names per WhatsApp Business Account
- Template names cannot be reused after deletion

### Registration Script — Run Once

```python
"""scripts/register_templates.py — Register Donna's WhatsApp templates."""
import asyncio
import httpx
from config import settings

WA_API = "https://graph.facebook.com/v18.0"

DONNA_TEMPLATES = [
    {
        "name": "donna_deadline",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "Heads up — {{1}} is due {{2}}. {{3}}",
                "example": {"body_text": [["CS2030S Lab 4", "tomorrow 11:59 PM",
                    "Here's the link."]]}
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Got it"},
                    {"type": "QUICK_REPLY", "text": "Remind me later"},
                ]
            }
        ]
    },
    {
        "name": "donna_grade_alert",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "New grade posted for {{1}}: {{2}}. {{3}}",
                "example": {"body_text": [["CS2030S Midterm", "78/100",
                    "Class median: 72."]]}
            }
        ]
    },
    {
        "name": "donna_schedule",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "Coming up: {{1}} at {{2}}. {{3}}",
                "example": {"body_text": [["CS2103T Lecture", "2:00 PM COM1-B103",
                    "Topic: Design Patterns."]]}
            }
        ]
    },
    {
        "name": "donna_daily_digest",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "Your day: {{1}}",
                "example": {"body_text": [["CS2030S lab 2pm, MA1521 tut 4pm. EE2026 due in 3 days."]]}
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Thanks"},
                    {"type": "QUICK_REPLY", "text": "Tell me more"},
                ]
            }
        ]
    },
    {
        "name": "donna_study_nudge",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "You have free time {{1}}. {{2}}",
                "example": {"body_text": [["between 2–4 PM",
                    "CS2103T iP increment due Friday."]]}
            }
        ]
    },
    {
        "name": "donna_email_alert",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "{{1}} emails worth checking. {{2}}",
                "example": {"body_text": [["3 new", "Prof Lee replied about project."]]}
            }
        ]
    },
    {
        "name": "donna_check_in",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "{{1}} {{2}}",
                "example": {"body_text": [["Good morning.",
                    "2 deadlines this week — want a game plan?"]]}
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Yes"},
                    {"type": "QUICK_REPLY", "text": "Not now"},
                ]
            }
        ]
    },
]

async def register_all():
    async with httpx.AsyncClient() as client:
        for tmpl in DONNA_TEMPLATES:
            resp = await client.post(
                f"{WA_API}/{settings.whatsapp_business_account_id}/message_templates",
                headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
                json={"language": "en", **tmpl},
            )
            data = resp.json()
            status = "OK" if "id" in data else "FAILED"
            print(f"  {status}: {tmpl['name']} — {data}")

if __name__ == "__main__":
    asyncio.run(register_all())
```

---

## 5. 24-Hour Window Routing Logic

The proactive sender must check whether the user is inside the 24-hour window before choosing the delivery method. This is the core change needed in `donna/brain/sender.py`.

```python
"""donna/brain/sender.py — Window-aware proactive message delivery."""

from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from db.models import ChatMessage, User, generate_uuid
from db.session import async_session
from tools.whatsapp import send_whatsapp_message, send_whatsapp_template

# Map Donna candidate categories → template names
CATEGORY_TEMPLATE_MAP = {
    "deadline_warning": "donna_deadline",
    "schedule_info":    "donna_schedule",
    "task_reminder":    "donna_deadline",
    "wellbeing":        "donna_check_in",
    "social":           "donna_check_in",
    "nudge":            "donna_study_nudge",
    "briefing":         "donna_daily_digest",
    "memory_recall":    "donna_check_in",
}


async def _is_window_open(user_id: str) -> bool:
    """Check if user messaged within the last 24 hours."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    async with async_session() as session:
        result = await session.execute(
            select(ChatMessage.created_at)
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= cutoff,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


async def _extract_template_params(candidate: dict) -> list[str]:
    """Extract variable values from a candidate message for template slots."""
    msg = candidate["message"]
    # Split into chunks that fit template variables
    # For donna_check_in (2 vars): first sentence + rest
    parts = msg.split(". ", 1)
    if len(parts) == 1:
        parts = [msg, ""]
    return [p.strip() for p in parts if p.strip()] or [msg]


async def send_proactive_message(user_id: str, candidate: dict) -> bool:
    """Send a proactive message, routing through template if outside 24h window."""
    async with async_session() as session:
        user = (await session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()

    if not user or not user.phone:
        return False

    message_text = candidate["message"]
    window_open = await _is_window_open(user_id)

    try:
        if window_open:
            # Inside 24h window — send freeform Donna-voice message
            await send_whatsapp_message(to=user.phone, text=message_text)
        else:
            # Outside window — must use approved template
            category = candidate.get("category", "nudge")
            template_name = CATEGORY_TEMPLATE_MAP.get(category, "donna_check_in")
            params = await _extract_template_params(candidate)
            await send_whatsapp_template(
                to=user.phone,
                template_name=template_name,
                params=params,
            )
    except Exception:
        logger.exception("Failed to send proactive message to %s", user.phone)
        return False

    # Persist as assistant message in chat history
    async with async_session() as session:
        session.add(ChatMessage(
            id=generate_uuid(),
            user_id=user_id,
            role="assistant",
            content=message_text,
        ))
        await session.commit()

    return True
```

---

## 6. Pricing (as of July 2025)

| Scenario | Cost |
|----------|------|
| Utility template within open 24h window | **FREE** |
| Utility template outside 24h window | $0.004 – $0.046 per message (varies by country) |
| Marketing template | $0.014 – $0.069 per message |
| Authentication template | $0.003 – $0.045 per message |
| Service conversation (user-initiated, within 24h) | **FREE** (first 1,000/month) |

**Cost optimization:** Donna's goal should be keeping users inside the 24-hour window. Every template with quick reply buttons is designed to elicit a response, which re-opens the free window. If students reply once a day, template costs approach zero.

---

## 7. Rate Limits and Scaling

| Limit | Value | Notes |
|-------|-------|-------|
| Messages per second | 80 msgs/sec (Cloud API) | Per phone number ID |
| Template creation | 100 per hour | Per WABA |
| Max templates | 250 names per WABA | Each name can have multiple languages |
| Messaging tier (unverified) | 250 unique users / 24h | Rolling window |
| Messaging tier 1 (verified) | 1,000 unique users / 24h | After business verification |
| Messaging tier 2 | 10,000 unique users / 24h | Based on quality rating |
| Messaging tier 3 | 100,000 unique users / 24h | Based on quality rating |
| Unlimited tier | No limit | High quality + volume history |

**Quality rating:** Meta assigns Green/Yellow/Red based on user feedback. If users block your number or report spam, your rating drops. A Red rating can restrict your account. Donna's `score_and_filter` rules (daily caps, quiet hours, cooldowns) are not just UX decisions — they protect your WhatsApp account health.

---

## 8. Required Configuration

Add to `.env`:

```bash
WHATSAPP_BUSINESS_ACCOUNT_ID=123456789012345  # WABA ID (different from phone number ID)

# WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID you already have
# are sufficient for sending. WABA_ID is only needed for
# template management (create/read/update/delete).
```

Add to `config.py`:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    whatsapp_business_account_id: str = ""  # For template management API
```

### Where to find your WABA ID

1. Go to Meta Business Suite → business.facebook.com
2. Navigate to Settings → Business Settings → Accounts → WhatsApp Accounts
3. Your WABA ID is displayed there (numeric, ~15 digits)
4. This is NOT the same as your Phone Number ID (which you already have)

---

## 9. Implementation Checklist

1. Add `whatsapp_business_account_id` to `config.py` and `.env`
2. Create `scripts/register_templates.py` with all Donna templates
3. Run the registration script and wait 24–48h for approval
4. Check template approval status via `GET /message_templates`
5. Update `donna/brain/sender.py` with 24-hour window check and routing logic
6. Add `_is_window_open()` helper that queries last user `ChatMessage` timestamp
7. Map candidate categories to template names via `CATEGORY_TEMPLATE_MAP`
8. Add `_extract_template_params()` to split LLM-generated messages into variable slots
9. Test: send proactive message to user who messaged >24h ago (should use template)
10. Test: send proactive message to user who messaged <24h ago (should use freeform)
11. Monitor WhatsApp quality rating in Meta Business Manager after launch
12. Track template delivery success rates vs freeform delivery rates

---

## Sources

- [Meta Business Management API — Message Templates](https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates)
- [WhatsApp Cloud API — Sending Templates](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates)
- [WhatsApp Pricing](https://developers.facebook.com/docs/whatsapp/pricing)
- [WhatsApp Template Guidelines](https://developers.facebook.com/docs/whatsapp/message-templates/guidelines)
- [WhatsApp Messaging Limits](https://developers.facebook.com/docs/whatsapp/messaging-limits)
- [WhatsApp Business Blog — Managing Templates](https://business.whatsapp.com/blog/manage-message-templates-whatsapp-business-api)
