import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from api.webhook import router as webhook_router
from api.auth import router as auth_router
from api.onboard import router as onboard_router
from agent.graph import build_graph
from agent.scheduler import start_scheduler, scheduler
from db.migrations import run_startup_migrations
from db.models import Base
from db.session import engine
from config import settings
from tools.whatsapp import close_client as close_wa_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on Supabase if they don't exist
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified")

        # Run startup migrations for new columns
        await run_startup_migrations(engine)
    except Exception:
        logger.exception("Failed to create tables — check DATABASE_URL")

    # Initialize LangGraph Postgres checkpointer
    try:
        pool = AsyncConnectionPool(conninfo=settings.database_url_direct, open=False, min_size=1, max_size=3)
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        # setup() uses CREATE INDEX CONCURRENTLY which cannot run in a transaction;
        # use a separate autocommit connection for the one-time migration
        async with await psycopg.AsyncConnection.connect(
            settings.database_url_direct, autocommit=True
        ) as setup_conn:
            await AsyncPostgresSaver(setup_conn).setup()
        app.state.agent = build_graph().compile(checkpointer=checkpointer)
        app.state.pool = pool
        logger.info("LangGraph Postgres checkpointer initialized")
    except Exception:
        logger.exception("Postgres checkpointer unavailable — compiling without persistence")
        app.state.agent = build_graph().compile()
        app.state.pool = None

    # Start Donna's proactive loop scheduler
    try:
        start_scheduler()
        logger.info("Donna scheduler started")
    except Exception:
        logger.exception("Failed to start Donna scheduler")

    yield

    scheduler.shutdown(wait=False)
    await close_wa_client()
    if app.state.pool:
        await app.state.pool.close()
    await engine.dispose()


app = FastAPI(title="Aura", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(auth_router, prefix="/auth")
app.include_router(onboard_router, prefix="/onboard")


@app.get("/health")
async def health():
    return {"status": "ok"}
