"""Register Donna's 8 WhatsApp message templates via the Business Management API.

Run once:
    cd app && python -m scripts.register_templates

Templates go into PENDING status and take 24-48h for Meta to approve.
Check status:  python -m scripts.register_templates --status
"""

import argparse
import asyncio
import sys

import httpx

# Allow running as `python -m scripts.register_templates` from app/
sys.path.insert(0, ".")
from config import settings  # noqa: E402

WA_API = "https://graph.facebook.com/v18.0"

# ── 8 Donna templates ────────────────────────────────────────────────────────

DONNA_TEMPLATES = [
    # 1. Deadline reminder (2 vars — assignment, due time)
    {
        "name": "donna_deadline_v2",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Heads up! You have an upcoming deadline — {{1}} is due {{2}}. "
                    "Make sure you don't miss it. Reply if you need a reminder closer to the time."
                ),
                "example": {
                    "body_text": [["CS2030S Lab 4", "tomorrow at 11:59 PM"]]
                },
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Got it"},
                    {"type": "QUICK_REPLY", "text": "Remind me later"},
                ],
            },
        ],
    },
    # 2. Grade alert (2 vars — course, score)
    {
        "name": "donna_grade_alert",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "New grade alert! Your score for {{1}} has been posted: {{2}}. "
                    "Check your course portal for full details and grade breakdown."
                ),
                "example": {
                    "body_text": [["CS2030S Midterm", "78 out of 100"]]
                },
            },
        ],
    },
    # 3. Schedule / upcoming event (2 vars — event, time+location)
    {
        "name": "donna_schedule",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Upcoming event reminder — {{1}} is happening at {{2}}. "
                    "Make sure you're prepared and on time!"
                ),
                "example": {
                    "body_text": [["CS2103T Lecture", "2:00 PM in COM1-B103"]]
                },
            },
        ],
    },
    # 4. Daily digest (1 var — formatted schedule)
    {
        "name": "donna_daily_digest",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Good morning! Here's your schedule for today: {{1}}. "
                    "Have a productive day ahead! Reply if you want more details."
                ),
                "example": {
                    "body_text": [
                        ["CS2030S lab at 2pm, MA1521 tutorial at 4pm, EE2026 assignment due in 3 days"]
                    ]
                },
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Thanks"},
                    {"type": "QUICK_REPLY", "text": "Tell me more"},
                ],
            },
        ],
    },
    # 5. Study nudge (1 var — suggestion)
    {
        "name": "donna_study_nudge",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Looks like you have some free time coming up. "
                    "Here's a suggestion to make the most of it — {{1}}. "
                    "Reply if you'd like help getting started."
                ),
                "example": {
                    "body_text": [
                        ["work on your CS2103T individual project increment which is due this Friday"]
                    ]
                },
            },
        ],
    },
    # 6. Email alert (1 var — summary)
    {
        "name": "donna_email_alert",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "You have some new emails that might need your attention. "
                    "Here's a quick summary — {{1}}. "
                    "Reply if you want more details on any of them."
                ),
                "example": {
                    "body_text": [
                        ["3 unread emails including a reply from Prof Lee about the group project deadline"]
                    ]
                },
            },
        ],
    },
    # 7. Check-in (1 var — context)
    {
        "name": "donna_check_in",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hey! Just checking in to see how things are going. {{1}} "
                    "Let me know if you need any help or want to plan your day."
                ),
                "example": {
                    "body_text": [
                        ["You have 2 deadlines this week and a quiz on Friday."]
                    ]
                },
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Yes please"},
                    {"type": "QUICK_REPLY", "text": "Not now"},
                ],
            },
        ],
    },
    # 8. Task reminder (1 var — task description)
    {
        "name": "donna_task_reminder",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Friendly reminder about a task you set — {{1}}. "
                    "Reply 'done' when you've finished or 'snooze' to be reminded later."
                ),
                "example": {
                    "body_text": [
                        ["Buy groceries from FairPrice, which you added yesterday"]
                    ]
                },
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Done"},
                    {"type": "QUICK_REPLY", "text": "Snooze"},
                ],
            },
        ],
    },
]

# ── Which templates have quick-reply buttons (for sender routing) ─────────

TEMPLATES_WITH_BUTTONS = {
    t["name"]
    for t in DONNA_TEMPLATES
    if any(c["type"] == "BUTTONS" for c in t["components"])
}


# ── Register ─────────────────────────────────────────────────────────────────

async def register_all():
    waba_id = settings.whatsapp_business_account_id
    if not waba_id:
        print("ERROR: WHATSAPP_BUSINESS_ACCOUNT_ID not set in .env")
        return

    url = f"{WA_API}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for tmpl in DONNA_TEMPLATES:
            resp = await client.post(
                url,
                headers=headers,
                json={"language": "en", **tmpl},
            )
            data = resp.json()
            ok = "id" in data
            tag = "OK" if ok else "FAIL"
            print(f"  [{tag}] {tmpl['name']} — {data}")


async def check_status():
    waba_id = settings.whatsapp_business_account_id
    if not waba_id:
        print("ERROR: WHATSAPP_BUSINESS_ACCOUNT_ID not set in .env")
        return

    url = f"{WA_API}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        data = resp.json()

    donna_names = {t["name"] for t in DONNA_TEMPLATES}
    for t in data.get("data", []):
        if t["name"] in donna_names:
            print(f"  {t['status']:10s}  {t['name']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage Donna WhatsApp templates")
    parser.add_argument("--status", action="store_true", help="Check template approval status")
    args = parser.parse_args()

    if args.status:
        asyncio.run(check_status())
    else:
        asyncio.run(register_all())
