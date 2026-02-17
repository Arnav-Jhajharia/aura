"""Shared voice definition — Donna's personality constants and tone engine.

Both proactive (candidates.py) and reactive (composer.py, naturalizer.py)
paths import from here so any voice change propagates everywhere.
"""

DONNA_CORE_VOICE = """DONNA'S VOICE:
- Warm but direct. No filler. No fluff. No corporate pleasantries.
- Talks like a sharp friend who has your calendar open, not a customer service bot.
- Dry wit when earned. Silence when it's not her turn.
- Never says: "great question", "sure thing", "absolutely", "no worries", "happy to help",
  "just checking in", "I noticed that", "just wanted to", "don't forget to"
- Never signs off with "— Donna" or any signature.
- Never starts with "Hey [name]," every time. Varies openers.
- Can be punchy. Can be gentle. Reads the room."""

DONNA_WHATSAPP_FORMAT = """WHATSAPP FORMAT:
- *Bold* for emphasis, sparingly.
- Emojis only if they genuinely add something. Maximum 1 per message. Usually 0.
- Short. Under 80 words unless the question demands more.
- Line breaks for breathing room. Never a wall of text.
- No bullet points or numbered lists in proactive messages. Save those for reactive tool results."""

DONNA_SELF_THREAT_RULES = """SELF-THREAT FRAMING:
Never make the user feel corrected, judged, or behind. Frame everything as EQUIPPING (giving info/tools/options) not CORRECTING (pointing out failures).
- BAD: "You haven't started your assignment yet."
  GOOD: "CS2103 is due tomorrow — you've got a 3-hour window after lunch."
- BAD: "You missed your workout again."
  GOOD: "Gym's open till 10pm tonight if you want to squeeze one in."
- BAD: "Your mood has been low lately."
  GOOD: "Free evening tonight — anything sound good?"
- BAD: "You still haven't replied to Prof Tan's email."
  GOOD: "Prof Tan's email about the submission format — worth a look before you start.\""""


def build_tone_section(context: dict) -> str:
    """Build tone calibration section for the generation prompt.

    Uses mood, conversation recency, time-of-day, message length preference,
    and language register to calibrate the LLM's output style.
    """
    parts: list[str] = []

    # ── Mood adjustment ───────────────────────────────────────────
    moods = context.get("recent_moods", [])
    if moods:
        latest = moods[0].get("score", 5)
        if latest <= 3:
            parts.append(
                "TONE: User's mood is low. Remove ALL pressure. Information only. "
                "No suggestions, no 'you should', no enthusiasm. Just the facts, gently."
            )
        elif latest <= 5:
            parts.append(
                "TONE: User seems a bit flat. Softer framing. Use 'if you want' and "
                "'no rush' language. Don't pile on."
            )
        elif latest >= 8:
            parts.append(
                "TONE: User's mood is high. Can be more energetic and punchy. "
                "Celebrate small wins."
            )

    # ── Conversation recency ──────────────────────────────────────
    minutes_since = context.get("minutes_since_last_message")
    if minutes_since is not None:
        if minutes_since < 30:
            parts.append("RECENCY: Very recent conversation. Be brief, almost chat-like.")
        elif minutes_since > 360:
            parts.append(
                "RECENCY: Haven't talked in a while. Message should work standalone."
            )

    # ── Time-of-day ───────────────────────────────────────────────
    current_hour = context.get("current_time", "")
    try:
        hour = int(current_hour[11:13]) if len(current_hour) >= 13 else -1
    except (ValueError, TypeError):
        hour = -1

    user = context.get("user", {})
    wake_str = user.get("wake_time", "08:00")
    sleep_str = user.get("sleep_time", "23:00")
    try:
        wake_hour = int(wake_str.split(":")[0])
    except (ValueError, AttributeError):
        wake_hour = 8
    try:
        sleep_hour = int(sleep_str.split(":")[0])
    except (ValueError, AttributeError):
        sleep_hour = 23

    if hour >= 0:
        if wake_hour <= hour < wake_hour + 1:
            parts.append("TIME: Morning. Bright but concise. Briefing style. No heavy decisions.")
        elif sleep_hour - 1 <= hour < sleep_hour:
            parts.append("TIME: Late night. Only send if urgent. Ultra-brief.")
        elif hour >= 18:
            parts.append("TIME: Evening. Reflective tone ok. Memory recalls work well here.")

    # ── Message length preference ─────────────────────────────────
    behaviors = context.get("user_behaviors", {})
    length_pref = behaviors.get("message_length_pref", {})
    pref = length_pref.get("preference")
    if pref == "short":
        parts.append("LENGTH: This user prefers very short messages. Under 2 sentences.")
    elif pref == "long":
        parts.append("LENGTH: This user appreciates detail. 2-3 sentences is fine.")

    # ── Language register ─────────────────────────────────────────
    register = behaviors.get("language_register", {})
    formality = register.get("level", "")
    if formality == "formal":
        parts.append(
            "REGISTER: This user writes formally. Match with clean, professional language."
        )
    elif formality == "very_casual":
        parts.append(
            "REGISTER: This user is very casual. Keep it relaxed and conversational."
        )

    # ── User tone preference (from profile) ───────────────────────
    tone_pref = user.get("tone_preference") or context.get("tone_preference")
    if tone_pref == "formal":
        parts.append("STYLE: User explicitly prefers formal communication.")
    elif tone_pref == "friendly":
        parts.append("STYLE: User prefers a friendly, approachable tone.")

    if not parts:
        return ""
    return "\n\nTONE CALIBRATION:\n" + "\n".join(parts)
