"""Template-aware parameter generation for outside-window messages.

When the 24h WhatsApp service window is closed, Donna must send pre-approved
template messages. This module uses a lightweight LLM call to fill template
parameter slots from the candidate's intent and signal data, instead of
fragile string-splitting.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings

logger = logging.getLogger(__name__)

llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key, temperature=0.3)

# Template text definitions (matching what's registered in Meta dashboard)
TEMPLATE_TEXTS = {
    "donna_deadline_v2": "Hey! {{1}} is due {{2}}. Might be worth getting ahead of it.",
    "donna_grade_alert": "{{1}} result: {{2}}.",
    "donna_schedule": "{{1}} — {{2}}.",
    "donna_daily_digest": "Here's your day: {{1}}",
    "donna_study_nudge": "{{1}}",
    "donna_email_alert": "{{1}}",
    "donna_check_in": "{{1}}",
    "donna_task_reminder": "{{1}}",
    "donna_habit_streak": "Day {{1}} of {{2}}! Keep going.",
    "donna_exam_reminder": "{{1}} exam in {{2}}.",
    "donna_class_reminder": "{{1}} in {{2}} — Room {{3}}.",
}

# Number of parameter slots per template
TEMPLATE_SLOT_COUNTS = {name: text.count("{{") for name, text in TEMPLATE_TEXTS.items()}


async def fill_template_params(candidate: dict, template_name: str) -> list[str]:
    """Use LLM to fill template parameter slots from candidate data.

    Returns a list of parameter strings matching the template's slot count.
    Falls back to naive splitting if LLM fails.
    """
    template_text = TEMPLATE_TEXTS.get(template_name)
    if not template_text:
        return [candidate["message"]]

    slot_count = TEMPLATE_SLOT_COUNTS.get(template_name, 1)

    # For single-slot templates, just use the message directly
    if slot_count == 1:
        return [candidate["message"][:1024]]

    system = (
        "You fill in template parameter slots for WhatsApp messages. "
        "Return ONLY a JSON object with a \"params\" key containing a list of strings. "
        "Each string fills one {{N}} slot in the template. No markdown, no explanation."
    )

    user = (
        f"Template: \"{template_text}\"\n"
        f"Number of slots: {slot_count}\n"
        f"Original message: \"{candidate['message']}\"\n"
        f"Category: {candidate.get('category', 'unknown')}\n"
        f"Signal data: {json.dumps(candidate.get('trigger_signals', []))}\n\n"
        f"Fill the {slot_count} parameter slots so the template reads naturally."
    )

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=user),
        ])

        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        parsed = json.loads(raw)
        params = parsed.get("params", [])

        if isinstance(params, list) and len(params) >= slot_count:
            return [str(p)[:1024] for p in params[:slot_count]]

    except Exception:
        logger.exception("Template filler LLM failed for %s", template_name)

    # Fallback: naive splitting
    return _naive_split(candidate["message"], slot_count)


def _naive_split(message: str, slot_count: int) -> list[str]:
    """Fallback: split message into slots by sentence boundaries."""
    if slot_count == 1:
        return [message[:1024]]

    # Try splitting on " — " first (Donna's typical joiner)
    parts = [p.strip() for p in message.split(" — ") if p.strip()]
    if len(parts) >= slot_count:
        result = parts[:slot_count - 1]
        result.append(" — ".join(parts[slot_count - 1:]))
        return [p[:1024] for p in result]

    # Fall back to ". " splitting
    parts = [p.strip() for p in message.split(". ") if p.strip()]
    if len(parts) >= slot_count:
        result = parts[:slot_count - 1]
        result.append(". ".join(parts[slot_count - 1:]))
        return [p[:1024] for p in result]

    # Pad with empty strings if needed
    return ([p[:1024] for p in parts] + [""] * slot_count)[:slot_count]
