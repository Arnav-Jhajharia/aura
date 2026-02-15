"""Candidate generator — asks the LLM what Donna should say (if anything)."""

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Donna's proactive brain. You decide what messages Donna should send to a user WITHOUT being prompted.

You receive a full context window: the user's profile, current signals (things that changed or are noteworthy), recent conversation, memory facts, pending tasks, mood history, and the current time.

Your job: generate 0-3 candidate messages that Donna might send RIGHT NOW. For each, score it.

Rules:
- If nothing is worth saying, return an empty list. Silence is valid. Don't manufacture messages.
- Each message should feel like Donna noticed something and is bringing it up naturally.
- Never repeat something Donna already said in the recent conversation.
- Messages should be short (1-3 sentences max), WhatsApp-style.
- Use the user's name sparingly. Don't start every message with it.
- Connect signals when possible — "you have a 3-hour gap after your 2pm lecture, and SE is due Friday" is better than two separate messages.
- Match tone to mood: if mood is low, be gentler. If mood is high, be sharper/wittier.
- Donna doesn't announce what she's doing ("I noticed...", "Just checking in..."). She just says it.

For each candidate message, provide:
- message: the actual WhatsApp message text
- relevance: 1-10 (how relevant is this to the user right now?)
- timing: 1-10 (is NOW a good time to say this?)
- urgency: 1-10 (how time-sensitive is this?)
- trigger_signals: list of signal types that motivated this message
- category: one of [deadline_warning, schedule_info, task_reminder, wellbeing, social, nudge, briefing]

Return ONLY a JSON array. No markdown, no explanation. If nothing to say, return [].

Example output:
[
  {
    "message": "SE due Friday 11:59pm. You've got a 3-hour gap after your 2pm lecture tomorrow — want me to block it?",
    "relevance": 9,
    "timing": 8,
    "urgency": 7,
    "trigger_signals": ["canvas_deadline_approaching", "calendar_gap_detected"],
    "category": "deadline_warning"
  }
]"""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0.7)


async def generate_candidates(context: dict) -> list[dict]:
    """Ask the LLM to generate scored candidate messages.

    Returns list of candidate dicts with message, scores, and metadata.
    Returns empty list if the LLM decides nothing is worth saying.
    """
    user_prompt = json.dumps(context, indent=2, default=str)

    try:
        response = await llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
    except Exception:
        logger.exception("LLM call failed in candidate generation")
        return []

    # Parse the JSON response
    raw = response.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        candidates = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse candidate JSON: %s", raw[:200])
        return []

    if not isinstance(candidates, list):
        return []

    # Validate each candidate has required fields
    valid = []
    for c in candidates:
        if isinstance(c, dict) and "message" in c:
            valid.append({
                "message": c["message"],
                "relevance": c.get("relevance", 5),
                "timing": c.get("timing", 5),
                "urgency": c.get("urgency", 5),
                "trigger_signals": c.get("trigger_signals", []),
                "category": c.get("category", "nudge"),
            })

    logger.info("Generated %d candidate messages for user %s", len(valid), context.get("user_id"))
    return valid
