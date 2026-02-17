"""Pre-send message validation for Donna's proactive messages.

Catches length violations, system prompt leakage, markdown artifacts,
and banned phrases before delivery.
"""

import logging
import re

logger = logging.getLogger(__name__)

# WhatsApp API limits
MAX_TEXT_LENGTH = 4096
MAX_TEMPLATE_PARAM_LENGTH = 1024

# Phrases that Donna should never say
BANNED_PHRASES = [
    "just checking in",
    "just wanted to",
    "i noticed that",
    "don't forget to",
    "great question",
    "sure thing",
    "absolutely",
    "no worries",
    "happy to help",
    "let me know if you need anything",
    "have a productive day",
    "have a great day",
    "hope you're having",
    "hope you're doing",
    "based on my analysis",
    "i recommend",
    "best regards",
    "— donna",
    "--donna",
    "- donna",
    "regards,",
]

# Patterns that suggest system prompt leakage
LEAKAGE_PATTERNS = [
    r"(?i)\bsystem\s*prompt\b",
    r"(?i)\byou\s+are\s+an?\s+ai\b",
    r"(?i)\bas\s+an?\s+ai\b",
    r"(?i)\blanguage\s+model\b",
    r"(?i)\bjson\s*(array|object|response)\b",
    r"(?i)\bcandidate\s+message\b",
    r"(?i)\brelevance:\s*\d",
    r"(?i)\btiming:\s*\d",
    r"(?i)\burgency:\s*\d",
]

# Markdown that doesn't render in WhatsApp
BAD_MARKDOWN = [
    r"#{1,6}\s",           # headings
    r"\[.*?\]\(.*?\)",     # links
    r"```",                # code blocks
    r"~~.*?~~",            # strikethrough
]


def validate_message(message: str) -> tuple[str, list[str]]:
    """Validate and clean a message before sending.

    Returns (cleaned_message, list_of_warnings).
    Warnings are logged but don't block sending.
    """
    warnings: list[str] = []
    cleaned = message

    if not cleaned or not cleaned.strip():
        return ("", ["empty_message"])

    # ── Length check ──────────────────────────────────────────────
    if len(cleaned) > MAX_TEXT_LENGTH:
        warnings.append(f"message_too_long ({len(cleaned)} chars)")
        cleaned = cleaned[:MAX_TEXT_LENGTH - 3] + "..."

    # ── Banned phrases ────────────────────────────────────────────
    lower = cleaned.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lower:
            warnings.append(f"banned_phrase: {phrase}")

    # ── System prompt leakage ─────────────────────────────────────
    for pattern in LEAKAGE_PATTERNS:
        if re.search(pattern, cleaned):
            warnings.append(f"possible_leakage: {pattern}")

    # ── Bad markdown cleanup ──────────────────────────────────────
    for pattern in BAD_MARKDOWN:
        if re.search(pattern, cleaned):
            warnings.append(f"bad_markdown: {pattern}")
            # Clean headings: "## Title" → "*Title*"
            cleaned = re.sub(r"#{1,6}\s+(.*?)$", r"*\1*", cleaned, flags=re.MULTILINE)
            # Clean links: [text](url) → text
            cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
            # Clean code blocks
            cleaned = cleaned.replace("```", "")
            # Clean strikethrough
            cleaned = re.sub(r"~~(.*?)~~", r"\1", cleaned)

    # ── Signature removal ─────────────────────────────────────────
    # Remove any trailing signature-like patterns
    cleaned = re.sub(r"\s*[-—]\s*Donna\s*$", "", cleaned, flags=re.IGNORECASE)

    # ── Emoji count enforcement (max 1) ──────────────────────────
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"   # symbols & pictographs
        "\U0001F680-\U0001F6FF"   # transport & map
        "\U0001F1E0-\U0001F1FF"   # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"   # supplemental symbols
        "\U0001FA00-\U0001FA6F"   # chess symbols
        "\U0001FA70-\U0001FAFF"   # symbols extended-A
        "\U00002600-\U000026FF"   # misc symbols
        "]+", re.UNICODE
    )
    emojis_found = emoji_pattern.findall(cleaned)
    if len(emojis_found) > 1:
        warnings.append(f"too_many_emojis ({len(emojis_found)} found, max 1)")
        # Keep only the first emoji, strip the rest
        first_emoji = emojis_found[0]
        first_pos = cleaned.index(first_emoji) + len(first_emoji)
        before = cleaned[:first_pos]
        after = emoji_pattern.sub("", cleaned[first_pos:])
        cleaned = before + after

    # ── Trailing whitespace cleanup ───────────────────────────────
    cleaned = cleaned.strip()

    if warnings:
        logger.warning("Message validation warnings: %s", warnings)

    return (cleaned, warnings)


def validate_template_params(params: list[str]) -> list[str]:
    """Validate template parameters, truncating if needed."""
    return [p[:MAX_TEMPLATE_PARAM_LENGTH] for p in params]


# ── Format-specific WhatsApp API constraints ──────────────────────────────────

BUTTON_BODY_MAX = 1024
BUTTON_TITLE_MAX = 20

LIST_BODY_MAX = 1024
LIST_MAX_ROWS = 10
LIST_TITLE_MAX = 24
LIST_DESC_MAX = 72

CTA_BODY_MAX = 1024
CTA_URL_MAX = 2000


def validate_format_constraints(candidate: dict, fmt: str) -> tuple[bool, str | None]:
    """Check format-specific WhatsApp API limits.

    Returns (valid, reason). If invalid, reason explains why.
    """
    message = candidate.get("message", "")

    if fmt == "button":
        if len(message) > BUTTON_BODY_MAX:
            return False, f"button body too long ({len(message)} > {BUTTON_BODY_MAX})"
        return True, None

    if fmt == "list":
        if len(message) > LIST_BODY_MAX:
            return False, f"list body too long ({len(message)} > {LIST_BODY_MAX})"
        lines = [ln.strip() for ln in message.split("\n") if ln.strip()]
        row_count = max(0, len(lines) - 1)  # first line is body
        if row_count > LIST_MAX_ROWS:
            return False, f"list has too many rows ({row_count} > {LIST_MAX_ROWS})"
        return True, None

    if fmt == "cta_url":
        if len(message) > CTA_BODY_MAX:
            return False, f"CTA body too long ({len(message)} > {CTA_BODY_MAX})"
        data = candidate.get("data", {})
        link = data.get("link", "") if isinstance(data, dict) else ""
        if link and len(link) > CTA_URL_MAX:
            return False, f"CTA URL too long ({len(link)} > {CTA_URL_MAX})"
        if link and not link.startswith(("http://", "https://")):
            return False, f"CTA URL invalid scheme: {link[:50]}"
        return True, None

    # text format — no special constraints beyond MAX_TEXT_LENGTH (already validated)
    return True, None
