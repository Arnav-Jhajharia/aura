import logging
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from config import settings
from db.models import MemoryFact, OAuthToken, User, generate_uuid
from db.session import async_session

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request bodies ────────────────────────────────────────────────

class CanvasTokenRequest(BaseModel):
    user_id: str  # phone number
    token: str


class NUSModsRequest(BaseModel):
    user_id: str  # phone number
    nusmods_url: str


# ── Helpers ───────────────────────────────────────────────────────

async def _get_or_create_user(phone: str) -> str:
    """Return the user UUID for the given phone, creating the user if needed."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if user:
            return user.id

        uid = generate_uuid()
        session.add(User(id=uid, phone=phone))
        await session.commit()
        return uid


async def _validate_canvas_token(token: str) -> bool:
    """Hit /api/v1/users/self to confirm the token works."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.canvas_base_url}/api/v1/users/self",
                headers={"Authorization": f"Bearer {token}"},
            )
        return resp.status_code == 200
    except Exception:
        return False


def _parse_nusmods_url(url: str) -> dict:
    """Parse a NUSMods share URL into semester + module list.

    Example URL:
    https://nusmods.com/timetable/sem-2/share?CS2103T=TUT:08,LEC:G17&CS2101=...

    Returns:
        {"semester": "sem-2", "modules": [{"code": "CS2103T", "lessons": "TUT:08,LEC:G17"}, ...]}
    """
    parsed = urlparse(url)
    # Path: /timetable/sem-2/share
    parts = [p for p in parsed.path.split("/") if p]
    semester = parts[1] if len(parts) >= 2 else "unknown"

    query = parse_qs(parsed.query)
    modules = []
    for code, values in query.items():
        modules.append({"code": code, "lessons": values[0] if values else ""})

    return {"semester": semester, "modules": modules}


# ── Endpoints ─────────────────────────────────────────────────────

@router.post("/canvas-token")
async def submit_canvas_token(body: CanvasTokenRequest):
    """Validate a Canvas PAT and store it for the user."""
    user_id = await _get_or_create_user(body.user_id)

    valid = await _validate_canvas_token(body.token)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Canvas token")

    async with async_session() as session:
        existing = await session.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == "canvas",
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            row.access_token = body.token
        else:
            session.add(OAuthToken(
                id=generate_uuid(),
                user_id=user_id,
                provider="canvas",
                access_token=body.token,
            ))

        # Clear pending action if set
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user:
            if user.pending_action in ("awaiting_canvas_token", "connect_canvas"):
                user.pending_action = None
            user.has_canvas = True
        await session.commit()

    logger.info("Canvas token stored for user %s (phone %s)", user_id, body.user_id)
    return {"ok": True}


@router.post("/nusmods")
async def submit_nusmods(body: NUSModsRequest):
    """Parse a NUSMods timetable URL and store module info as memory facts."""
    if "nusmods.com/timetable/" not in body.nusmods_url:
        raise HTTPException(status_code=400, detail="Invalid NUSMods URL")

    user_id = await _get_or_create_user(body.user_id)
    parsed = _parse_nusmods_url(body.nusmods_url)
    modules = parsed["modules"]
    semester = parsed["semester"]

    if not modules:
        raise HTTPException(status_code=400, detail="No modules found in URL")

    module_codes = [m["code"] for m in modules]

    async with async_session() as session:
        # Store as a single memory fact with all module info
        session.add(MemoryFact(
            id=generate_uuid(),
            user_id=user_id,
            fact=f"NUS timetable ({semester}): taking {', '.join(module_codes)}. Full schedule URL: {body.nusmods_url}",
            category="context",
            confidence=1.0,
        ))

        # Store individual module facts for granular recall
        for mod in modules:
            lessons = mod["lessons"].replace(",", ", ") if mod["lessons"] else "no lesson info"
            session.add(MemoryFact(
                id=generate_uuid(),
                user_id=user_id,
                fact=f"Taking {mod['code']} this {semester} — lessons: {lessons}",
                category="context",
                confidence=1.0,
            ))

        # Set NUSMods imported flag
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.nusmods_imported = True

        await session.commit()

    logger.info(
        "NUSMods timetable stored for user %s: %s (%d modules)",
        user_id, semester, len(modules),
    )
    return {"ok": True, "modules": module_codes, "semester": semester}
