import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from db.models import Expense, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)


async def log_expense(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Log an expense with auto-categorization."""
    entities = entities or {}
    amounts = entities.get("amounts", [])
    amount = kwargs.get("amount") or (float(amounts[0]) if amounts else 0.0)
    category = kwargs.get("category", "other")
    description = kwargs.get("description", "")

    expense = Expense(
        id=generate_uuid(),
        user_id=user_id,
        amount=amount,
        category=category,
        description=description,
    )

    async with async_session() as session:
        session.add(expense)
        await session.commit()

        # Weekly total
        week_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.user_id == user_id,
                Expense.created_at >= week_ago,
            )
        )
        weekly_total = result.scalar() or 0.0

    return {
        "id": expense.id,
        "amount": amount,
        "category": category,
        "weekly_total": round(weekly_total, 2),
    }


async def get_expense_summary(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Get expense summary for a given period (week or month)."""
    period = kwargs.get("period", "week")
    days = 7 if period == "week" else 30
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    async with async_session() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.user_id == user_id,
                Expense.created_at >= cutoff,
            )
        )
        expenses = result.scalars().all()

    total = sum(e.amount for e in expenses)
    by_category: dict[str, float] = {}
    for e in expenses:
        cat = e.category or "other"
        by_category[cat] = by_category.get(cat, 0) + e.amount

    return {
        "period": period,
        "total": round(total, 2),
        "by_category": {k: round(v, 2) for k, v in by_category.items()},
        "transaction_count": len(expenses),
    }
