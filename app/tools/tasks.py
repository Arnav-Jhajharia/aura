import logging
from datetime import datetime

from sqlalchemy import select

from db.models import Task, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)


async def create_task(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Create a new task for the user."""
    entities = entities or {}
    title = kwargs.get("title") or " ".join(entities.get("topics", [])) or "Untitled task"
    due_date_str = (entities.get("dates") or [None])[0]
    priority = kwargs.get("priority", 2)

    due_date = None
    if due_date_str:
        try:
            due_date = datetime.fromisoformat(due_date_str)
        except (ValueError, TypeError):
            pass

    task = Task(
        id=generate_uuid(),
        user_id=user_id,
        title=title,
        due_date=due_date,
        priority=priority,
    )

    async with async_session() as session:
        session.add(task)
        await session.commit()

    return {
        "id": task.id,
        "title": task.title,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "priority": task.priority,
    }


async def get_tasks(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Get tasks for the user. Defaults to pending tasks."""
    status = kwargs.get("status", "pending")

    async with async_session() as session:
        query = select(Task).where(Task.user_id == user_id)
        if status != "all":
            query = query.where(Task.status == status)
        query = query.order_by(Task.due_date.asc().nullslast()).limit(20)

        result = await session.execute(query)
        tasks = result.scalars().all()

    return [
        {
            "id": t.id,
            "title": t.title,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "priority": t.priority,
            "status": t.status,
        }
        for t in tasks
    ]


async def complete_task(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Mark a task as completed."""
    task_id = kwargs.get("task_id")
    if not task_id:
        return {"error": "task_id required"}

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.id == task_id, Task.user_id == user_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            return {"error": "task not found"}

        task.status = "done"
        task.completed_at = datetime.utcnow()
        await session.commit()

    return {"success": True, "title": task.title}
