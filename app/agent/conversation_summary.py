"""Conversation summary — compress older history into a rolling summary."""

import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from config import settings
from db.models import ChatMessage, User
from db.session import async_session

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """Summarize this conversation between a user and Donna (an AI assistant).
Keep it concise — 3-5 bullet points covering the key topics, decisions, and any
information the user shared that Donna should remember for future context.

Previous summary (if any):
{previous_summary}

New conversation to incorporate:
{conversation}

Return only the updated summary as bullet points. No preamble."""

# Summarize after every 10 new messages since last summary
SUMMARY_INTERVAL = 10

llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key)


async def maybe_update_summary(user_id: str) -> None:
    """Check if a conversation summary update is due and generate one if so."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return

        total = user.total_messages or 0
        last_summarized = getattr(user, "conversation_summary_message_count", 0) or 0

        if total - last_summarized < SUMMARY_INTERVAL:
            return

        # Fetch messages since last summary (up to 20)
        history_result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(20)
        )
        rows = history_result.scalars().all()
        if not rows:
            return

        lines = []
        for m in reversed(rows):
            prefix = "User" if m.role == "user" else "Donna"
            lines.append(f"{prefix}: {m.content}")
        conversation_text = "\n".join(lines)

        previous = user.conversation_summary or "(none)"

        try:
            response = await llm.ainvoke([
                SystemMessage(content=SUMMARY_PROMPT.format(
                    previous_summary=previous,
                    conversation=conversation_text,
                )),
                HumanMessage(content="Update the summary."),
            ])
            user.conversation_summary = response.content.strip()
            user.conversation_summary_message_count = total
            await session.commit()
            logger.info("Updated conversation summary for user %s", user_id)
        except Exception:
            logger.exception("Failed to update conversation summary for %s", user_id)
