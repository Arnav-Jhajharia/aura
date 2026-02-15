import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from config import settings
from db.models import OAuthToken
from db.session import async_session

logger = logging.getLogger(__name__)


def _parse_link_next(link_header: str | None) -> str | None:
    """Extract the 'next' page URL from Canvas Link header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part, re.I)
        if match:
            return match.group(1)
    return None


async def _fetch_all_pages(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    params: dict | None = None,
) -> list:
    """Fetch all paginated results from a Canvas API endpoint."""
    all_items: list = []
    next_url: str | None = url
    request_params = params.copy() if params else {}

    while next_url:
        resp = await client.get(next_url, headers=headers, params=request_params)
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Canvas API error: {resp.status_code}",
                request=resp.request,
                response=resp,
            )
        items = resp.json()
        all_items.extend(items)
        request_params = {}
        next_url = _parse_link_next(resp.headers.get("link"))

    return all_items


async def _get_canvas_token(user_id: str) -> str | None:
    """Retrieve the user's Canvas PAT from the database."""
    async with async_session() as session:
        result = await session.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == "canvas",
            )
        )
        token = result.scalar_one_or_none()
    return token.access_token if token else None


async def get_canvas_assignments(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Get upcoming assignments from Canvas LMS.

    Returns list of {title, course, due_date, points, submitted}.
    """
    token = await _get_canvas_token(user_id)
    if not token:
        return [{"error": "Canvas not connected. Send /connect canvas to set up."}]

    days_ahead = kwargs.get("days_ahead", 7)
    base_url = settings.canvas_base_url
    url = f"{base_url}/api/v1/users/self/upcoming_events"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"per_page": 100}

    try:
        async with httpx.AsyncClient() as client:
            events = await _fetch_all_pages(client, url, headers, params)
    except httpx.HTTPStatusError as e:
        return [{"error": f"Canvas API error: {e.response.status_code}"}]
    except Exception as e:
        return [{"error": f"Canvas API request failed: {e}"}]

    cutoff = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    assignments = []
    for event in events:
        assignment = event.get("assignment", {})
        if not assignment:
            continue
        due = assignment.get("due_at")
        if due:
            due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
            if due_dt > cutoff:
                continue

        assignments.append({
            "title": assignment.get("name", ""),
            "course": event.get("context_name", ""),
            "due_date": due,
            "points": assignment.get("points_possible"),
            "submitted": assignment.get("has_submitted_submissions", False),
        })

    return assignments


async def get_canvas_grades(user_id: str, entities: dict = None, **kwargs) -> list[dict]:
    """Get recent grades from Canvas.

    Returns list of {assignment, course, score, points_possible}.
    """
    token = await _get_canvas_token(user_id)
    if not token:
        return [{"error": "Canvas not connected."}]

    base_url = settings.canvas_base_url
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient() as client:
            courses = await _fetch_all_pages(
                client,
                f"{base_url}/api/v1/courses",
                headers,
                params={"enrollment_state": "active", "per_page": 100},
            )
            grades = []

            for course in courses:
                course_id = course["id"]
                try:
                    subs = await _fetch_all_pages(
                        client,
                        f"{base_url}/api/v1/courses/{course_id}/students/submissions",
                        headers,
                        params={"student_ids[]": "self", "per_page": 100, "order": "graded_at"},
                    )
                except httpx.HTTPStatusError:
                    continue

                for sub in subs:
                    if sub.get("score") is not None:
                        grades.append({
                            "assignment": sub.get("assignment", {}).get("name", "Unknown"),
                            "course": course.get("name", ""),
                            "score": sub.get("score"),
                            "points_possible": sub.get("assignment", {}).get("points_possible"),
                        })

            return grades[:20]
    except httpx.HTTPStatusError as e:
        return [{"error": f"Canvas API error: {e.response.status_code}"}]
