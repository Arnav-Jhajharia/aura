"""Candidate generator — asks the LLM what Donna should say (if anything)."""

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config import settings
from donna.voice import (
    DONNA_CORE_VOICE,
    DONNA_SELF_THREAT_RULES,
    DONNA_WHATSAPP_FORMAT,
    build_tone_section,
)

logger = logging.getLogger(__name__)

PROACTIVE_RULES = """You are the proactive brain behind Donna, a WhatsApp assistant for university students. You decide what (if anything) Donna texts a user RIGHT NOW.

You receive the user's full context: signals, calendar, tasks, conversation history, memory, mood.

CORE RULE: Return [] unless you have something SPECIFIC and ACTIONABLE to say. Silence is always better than a vague message. Most of the time you should return [].

WHAT MAKES A GOOD MESSAGE:
- References a CONCRETE thing: an assignment name + due date, a class time + room, a specific email from a specific person, a task with a real title
- Is ACTIONABLE: tells them something they can do, not just observes something
- Is SHORT: 1-2 sentences. WhatsApp, not email.
- Connects 2+ signals when possible: "CS2030S lab due tomorrow 11:59pm — you're free 2-5pm today"

WHAT MAKES A BAD MESSAGE (never generate these):
- Vague observations: "you've got some open loops", "things may need revisiting"
- Stating facts without action: "Google is connected", "you have tasks pending"
- Generic encouragement: "I'm here", "let me know if you need anything", "have a productive day"
- Meta-commentary: "I noticed...", "Just checking in...", "Wanted to remind you..."
- Signing off: never end with "— Donna" or any signature
- Listing things the user already knows without adding value
- Anything you'd be embarrassed to receive as a text from a friend

SCORING GUIDE:
- relevance: Is this actually useful RIGHT NOW? (not "eventually useful")
- timing: Would this be better said later? If yes, score low and don't send.
- urgency: Does the user need to act soon? A deadline in 3 days is a 4, not an 8.

ACTION TYPE:
Set action_type to "button_prompt" when the message naturally invites a yes/no or choice response (e.g., "want me to block this time?" or "should I snooze this?"). Otherwise use "text".

CATEGORY EXAMPLES:

deadline_warning:
  "CS2103 Assignment 3 due tomorrow 11:59pm. You're free 3-5 today."

schedule_info:
  "Your 2pm got moved to 3pm. Same room."

task_reminder:
  "That MA2001 practice set you added yesterday — still on the list."

wellbeing (trust: established+):
  "Free evening tonight. That bouldering place you mentioned is open till 10."
  "Busy week. The MA2001 practice set isn't graded — could push it to the weekend?"

social (trust: deep):
  "Noor's birthday is Saturday — just flagging in case you want to plan something."
  "Free Saturday afternoon — could grab lunch with the CS2103 group."

nudge:
  "Gym's open till 10pm if you want to squeeze one in."

briefing:
  "Wednesday. CS2103 10-12, IS1108 tutorial at 3. MA2001 due Friday. Nothing else."
  "Light day. Just IS1108 at 3. Could get ahead on CS2103."

memory_recall (trust: established+):
  "That ramen place near PGP you mentioned — Noor was interested too. Free Saturday."
  "Prof Tan's office hours are 2-4pm today if you still wanted to ask about the project."

grade_alert:
  "MA2001 midterm: 78/100. Above average based on past semesters."

email_alert:
  "Prof Tan emailed about the CS2103 submission format change. Worth a look."

habit:
  "Day 14 of running. Two weeks. Not bad."
  "Gym's open till 10pm if you want to keep the streak going."

Return ONLY a JSON array. No markdown, no explanation.

[
  {
    "message": "CS2030S Lab 4 due tomorrow 11:59pm. You're free 2-5pm today if you want to knock it out.",
    "relevance": 9,
    "timing": 8,
    "urgency": 7,
    "trigger_signals": ["canvas_deadline_approaching", "calendar_gap_detected"],
    "category": "deadline_warning",
    "action_type": "button_prompt"
  }
]

Return [] if nothing specific warrants a message. This is the correct answer most of the time."""

llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0.7)


def _build_trust_instructions(context: dict) -> str:
    """Build trust-level calibration instructions for the system prompt."""
    trust = context.get("trust_info")
    if not trust:
        return ""

    level = trust.get("level", "new")
    instructions = {
        "new": (
            "\n\nTRUST LEVEL: NEW USER\n"
            "This user is new to Donna. Be conservative:\n"
            "- Only message for clearly time-sensitive or high-value signals\n"
            "- Keep messages shorter. Prove value before taking space.\n"
            "- Don't reference past patterns or assume familiarity\n"
            "- Err on the side of silence"
        ),
        "building": (
            "\n\nTRUST LEVEL: BUILDING\n"
            "Donna is getting to know this user. Moderate approach:\n"
            "- Can surface schedule optimizations and deadline reminders\n"
            "- Start connecting signals (calendar + assignments)\n"
            "- Still conservative on wellbeing/social messages"
        ),
        "established": (
            "\n\nTRUST LEVEL: ESTABLISHED\n"
            "This user trusts Donna. Normal proactive behavior:\n"
            "- Full range of message types including nudges and memory recalls\n"
            "- Can reference past conversations and patterns\n"
            "- Wellbeing check-ins are appropriate"
        ),
        "deep": (
            "\n\nTRUST LEVEL: DEEP\n"
            "Long-term user with deep trust:\n"
            "- Can be more direct and witty\n"
            "- Proactive about subtle patterns (mood, habits, social)\n"
            "- Reference shared history naturally\n"
            "- Full Donna personality"
        ),
    }
    return instructions.get(level, "")


def _build_dynamic_sections(context: dict) -> str:
    """Build feedback + patterns + behavioral model sections for the system prompt."""
    parts: list[str] = []

    # Feedback section
    feedback = context.get("feedback_summary")
    if feedback and feedback.get("total_sent", 0) > 0:
        rates = feedback.get("engagement_by_category", {})
        if rates:
            lines = [f"  - {cat}: {rate:.0%} engagement" for cat, rate in rates.items()]
            parts.append(
                "\n\nFEEDBACK DATA (last 30 days):\n"
                f"Total messages sent: {feedback['total_sent']}\n"
                f"Overall engagement rate: {feedback.get('engagement_rate', 0):.0%}\n"
                "Engagement by category:\n" + "\n".join(lines) + "\n"
                "Prioritize categories with higher engagement. "
                "Avoid categories the user consistently ignores."
            )

    # Patterns section
    patterns = context.get("behavioral_patterns", [])
    if patterns:
        lines = [f"  - {p}" for p in patterns[:5]]
        parts.append("\n\nUSER BEHAVIORAL PATTERNS:\n" + "\n".join(lines))

    # User behavioral model (from nightly reflection)
    behaviors = context.get("user_behaviors", {})
    if behaviors:
        beh_lines: list[str] = []
        if "active_hours" in behaviors:
            peaks = behaviors["active_hours"].get("peak_hours", [])
            if peaks:
                beh_lines.append(
                    f"  - Peak hours: {', '.join(str(h) + ':00' for h in peaks)}"
                )
        if "message_length_pref" in behaviors:
            pref = behaviors["message_length_pref"].get("preference", "unknown")
            beh_lines.append(f"  - Message length preference: {pref}")
        if "response_speed" in behaviors:
            avg = behaviors["response_speed"].get("avg")
            if avg:
                beh_lines.append(f"  - Avg response time: {round(avg / 60, 1)} min")
        if "language_register" in behaviors:
            reg = behaviors["language_register"].get("level", "unknown")
            beh_lines.append(f"  - Language register: {reg}")
        if beh_lines:
            parts.append("\n\nUSER BEHAVIORAL MODEL:\n" + "\n".join(beh_lines))

    # ── Engagement trends (from feedback metrics) ──────────────────────
    trends = context.get("engagement_trends", {})
    if trends:
        trend_lines = []
        for cat, trend in trends.items():
            direction = trend.get("direction", "stable")
            current = trend.get("current_rate", 0)
            trend_lines.append(f"  - {cat}: {current:.0%} ({direction})")
        parts.append(
            "\n\nENGAGEMENT TRENDS (vs. 2 weeks ago):\n" + "\n".join(trend_lines) + "\n"
            "Rising categories: lean into them. Falling categories: reduce frequency or change approach."
        )

    # ── Category preferences (from feedback metrics) ───────────────────
    cat_prefs = context.get("category_preferences", {})
    if cat_prefs:
        pref_lines = [f"  - {cat}: {score:.2f}" for cat, score in sorted(
            cat_prefs.items(), key=lambda x: x[1], reverse=True)]
        parts.append(
            "\n\nCATEGORY PREFERENCE SCORES (0=ignored, 1=loved):\n" + "\n".join(pref_lines) + "\n"
            "Categories scored below 0.2 should be avoided unless urgency >= 8."
        )

    # ── Suppressed categories ──────────────────────────────────────────
    suppression = context.get("category_suppression", {})
    suppressed = suppression.get("suppressed", {})
    if suppressed:
        sup_list = [f"  - {cat} (reason: {info.get('reason', 'unknown')})"
                    for cat, info in suppressed.items()]
        parts.append(
            "\n\nSUPPRESSED CATEGORIES (DO NOT generate messages in these categories):\n"
            + "\n".join(sup_list)
        )

    # ── Format preference hint ─────────────────────────────────────────
    fmt_pref = context.get("format_preferences", {})
    meta_fmt = context.get("meta_format_preference", {})
    preferred = meta_fmt.get("preferred_format") or fmt_pref.get("preferred_format")
    if preferred == "button":
        parts.append(
            "\n\nFORMAT HINT: This user engages more with button messages. "
            "Use action_type 'button_prompt' when the message naturally invites a choice."
        )
    elif preferred == "list":
        parts.append(
            "\n\nFORMAT HINT: This user engages more with list messages. "
            "Use structured multi-item messages when appropriate."
        )

    return "".join(parts)


async def generate_candidates(context: dict) -> list[dict]:
    """Ask the LLM to generate scored candidate messages.

    Returns list of candidate dicts with message, scores, and metadata.
    Returns empty list if the LLM decides nothing is worth saying.
    """
    system = "\n\n".join([
        PROACTIVE_RULES,
        DONNA_CORE_VOICE,
        DONNA_WHATSAPP_FORMAT,
        DONNA_SELF_THREAT_RULES,
    ])
    system += _build_trust_instructions(context)
    system += _build_dynamic_sections(context)
    system += build_tone_section(context)

    user_prompt = json.dumps(context, indent=2, default=str)

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system),
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
                "action_type": c.get("action_type", "text"),
            })

    logger.info("Generated %d candidate messages for user %s", len(valid), context.get("user_id"))
    return valid
