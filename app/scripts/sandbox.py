#!/usr/bin/env python3
"""Interactive E2E sandbox — test all 4 layers with real LLM calls.

Usage:
    cd app
    python -m scripts.sandbox

What it does:
    - Spins up an in-memory SQLite DB (no Postgres needed)
    - Creates a test user with realistic data (tasks, moods, memory, behaviors)
    - Captures WhatsApp sends (prints instead of calling the API)
    - Uses your real OpenAI key for LLM calls (intent, composer, candidates, etc.)
    - Interactive REPL: type messages as the user, or use commands

Commands:
    /donna              — Run Donna's proactive loop (signals → brain → message)
    /donna deadline     — Inject a Canvas deadline signal, then run Donna
    /donna morning      — Inject morning briefing signals, then run Donna
    /donna mood         — Inject low-mood + evening signal, then run Donna
    /donna grade        — Inject grade posted signal, then run Donna
    /donna email        — Inject important email signal, then run Donna
    /donna habit        — Inject habit streak signal, then run Donna
    /context            — Show the full context Donna builds for this user
    /snapshot           — Show the unified user model snapshot
    /signals            — List all signals that would fire right now
    /memory             — Show all memory facts for the user
    /behaviors          — Show computed behavioral model
    /history            — Show recent chat history
    /reset              — Reset the DB and re-seed data
    /quit               — Exit
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(name)-30s %(levelname)-5s %(message)s",
)
# Quiet noisy loggers
for name in ("httpx", "httpcore", "openai", "langchain", "langsmith"):
    logging.getLogger(name).setLevel(logging.WARNING)

logger = logging.getLogger("sandbox")

# ── Imports (after logging setup) ────────────────────────────────────────
from db.models import (  # noqa: E402
    Base,
    ChatMessage,
    Expense,
    Habit,
    MemoryFact,
    MoodLog,
    Task,
    User,
    UserBehavior,
    UserEntity,
    generate_uuid,
)

# ── All modules that import async_session ────────────────────────────────
_MODULES_TO_PATCH = [
    "db.session",
    "donna.signals.internal",
    "donna.signals.calendar",
    "donna.signals.canvas",
    "donna.signals.email",
    "donna.signals.dedup",
    "donna.signals.collector",
    "donna.brain.context",
    "donna.brain.sender",
    "donna.brain.rules",
    "donna.brain.prefilter",
    "donna.brain.trust",
    "donna.brain.feedback",
    "donna.brain.template_filler",
    "donna.brain.validators",
    "donna.memory.entities",
    "donna.memory.recall",
    "donna.memory.patterns",
    "tools.memory_search",
    "agent.nodes.memory",
    "agent.nodes.context",
    "agent.nodes.ingress",
    "agent.nodes.onboarding",
    "agent.nodes.token_collector",
    "donna.memory.entity_store",
    "donna.brain.behaviors",
    "donna.reflection",
    "donna.user_model",
]

# ── Globals ──────────────────────────────────────────────────────────────
TEST_PHONE = "+6591234567"
TEST_USER_ID = None  # Set during seed
_engine = None
_session_factory = None
_patches = []

# Track WhatsApp sends
wa_sends: list[dict] = []


# ── Colors ───────────────────────────────────────────────────────────────
class C:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _print_donna(text: str):
    print(f"\n{C.GREEN}{C.BOLD}Donna:{C.RESET} {C.GREEN}{text}{C.RESET}")


def _print_system(text: str):
    print(f"{C.DIM}{text}{C.RESET}")


def _print_section(title: str, content: str):
    print(f"\n{C.CYAN}{C.BOLD}── {title} ──{C.RESET}")
    print(content)


# ── WhatsApp mocks ───────────────────────────────────────────────────────
async def _mock_send_message(to: str, text: str):
    wa_sends.append({"type": "text", "to": to, "text": text})
    _print_donna(text)
    return {"messages": [{"id": "mock_msg_id"}]}


async def _mock_send_buttons(to: str, body: str, buttons: list):
    labels = " | ".join(f"[{b['title']}]" for b in buttons)
    wa_sends.append({"type": "buttons", "to": to, "body": body, "buttons": buttons})
    _print_donna(f"{body}\n  {C.YELLOW}{labels}{C.RESET}")
    return {"messages": [{"id": "mock_msg_id"}]}


async def _mock_send_template(to: str, template_name: str, params: list, button_payloads=None):
    wa_sends.append({"type": "template", "to": to, "template": template_name, "params": params})
    _print_donna(f"[Template: {template_name}] params={params}")
    return {"messages": [{"id": "mock_msg_id"}]}


async def _mock_send_list(to: str, body: str, button_text: str, sections: list):
    wa_sends.append({"type": "list", "to": to, "body": body, "sections": sections})
    lines = [body]
    for s in sections:
        lines.append(f"  {C.BOLD}{s.get('title', '')}{C.RESET}")
        for r in s.get("rows", []):
            lines.append(f"    • {r['title']}" + (f" — {r.get('description', '')}" if r.get("description") else ""))
    _print_donna("\n".join(lines))
    return {"messages": [{"id": "mock_msg_id"}]}


async def _mock_send_cta(to: str, body: str, button_text: str, url: str):
    wa_sends.append({"type": "cta", "to": to, "body": body, "url": url})
    _print_donna(f"{body}\n  {C.YELLOW}[{button_text}] → {url}{C.RESET}")
    return {"messages": [{"id": "mock_msg_id"}]}


async def _mock_react(to: str, message_id: str, emoji: str = "👍"):
    wa_sends.append({"type": "reaction", "to": to, "emoji": emoji})
    print(f"  {C.DIM}(reacted with {emoji}){C.RESET}")
    return {}


# ── DB setup ─────────────────────────────────────────────────────────────
async def _setup_db():
    global _engine, _session_factory
    _engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


def _patch_all():
    """Redirect async_session in all modules to our in-memory DB."""
    global _patches
    for p in _patches:
        p.stop()
    _patches = []
    for mod in _MODULES_TO_PATCH:
        try:
            p = patch(f"{mod}.async_session", _session_factory)
            p.start()
            _patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass

    # Mock WhatsApp API
    _patches.append(patch("tools.whatsapp.send_whatsapp_message", side_effect=_mock_send_message))
    _patches.append(patch("tools.whatsapp.send_whatsapp_buttons", side_effect=_mock_send_buttons))
    _patches.append(patch("tools.whatsapp.send_whatsapp_template", side_effect=_mock_send_template))
    _patches.append(patch("tools.whatsapp.send_whatsapp_list", side_effect=_mock_send_list))
    _patches.append(patch("tools.whatsapp.send_whatsapp_cta_button", side_effect=_mock_send_cta))
    _patches.append(patch("tools.whatsapp.react_to_message", side_effect=_mock_react))

    # Also patch in sender.py and memory.py where they import directly
    _patches.append(patch("donna.brain.sender.send_whatsapp_message", side_effect=_mock_send_message))
    _patches.append(patch("donna.brain.sender.send_whatsapp_buttons", side_effect=_mock_send_buttons))
    _patches.append(patch("donna.brain.sender.send_whatsapp_template", side_effect=_mock_send_template))
    _patches.append(patch("donna.brain.sender.send_whatsapp_list", side_effect=_mock_send_list))
    _patches.append(patch("donna.brain.sender.send_whatsapp_cta_button", side_effect=_mock_send_cta))
    _patches.append(patch("agent.nodes.memory.send_whatsapp_message", side_effect=_mock_send_message))
    _patches.append(patch("agent.nodes.memory.react_to_message", side_effect=_mock_react))

    # Mock embedding calls (no OpenAI embeddings endpoint needed)
    async def _mock_embed(text):
        return [0.0] * 1536
    _patches.append(patch("donna.memory.embeddings.embed_text", side_effect=_mock_embed))
    _patches.append(patch("agent.nodes.memory.embed_text", side_effect=_mock_embed))

    for p in _patches[len([m for m in _MODULES_TO_PATCH]):]:
        p.start()


async def _seed_data():
    """Create a realistic test user with data across all layers."""
    global TEST_USER_ID
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    TEST_USER_ID = generate_uuid()

    async with _session_factory() as session:
        # ── User ─────────────────────────────────────────────────
        user = User(
            id=TEST_USER_ID,
            phone=TEST_PHONE,
            name="Rina",
            timezone="Asia/Singapore",
            wake_time="08:00",
            sleep_time="23:30",
            reminder_frequency="normal",
            tone_preference="casual",
            onboarding_complete=True,
            onboarding_step="complete",
            total_messages=47,
            last_active_at=now - timedelta(hours=2),
        )
        session.add(user)

        # ── Chat history (recent conversation) ───────────────────
        history = [
            ("user", "hey what's due this week", now - timedelta(hours=6)),
            ("assistant", "CS2103 Assignment 3 due Friday 11:59pm. MA2001 Tutorial 5 due Wednesday.", now - timedelta(hours=6, minutes=-1)),
            ("user", "ugh haven't started cs2103 yet", now - timedelta(hours=5, minutes=50)),
            ("assistant", "You've got a 3-hour block tomorrow afternoon. Could knock out a chunk then.", now - timedelta(hours=5, minutes=49)),
            ("user", "ya maybe. had ramen with noor today, that new place near pgp was fire", now - timedelta(hours=2)),
            ("assistant", "Noted. I'll remember the PGP ramen spot.", now - timedelta(hours=2, minutes=-1)),
        ]
        for role, content, ts in history:
            session.add(ChatMessage(
                id=generate_uuid(), user_id=TEST_USER_ID,
                role=role, content=content, created_at=ts,
            ))

        # ── Memory facts ─────────────────────────────────────────
        facts = [
            ("Takes CS2103T, CS2101, MA2001, IS1108 this semester", "context"),
            ("Likes ramen — tried new place near PGP with Noor", "preference"),
            ("Tends to procrastinate on CS2103 assignments", "pattern"),
            ("Gym routine: usually goes around 6-7pm", "pattern"),
            ("Noor is a close friend, same faculty", "relationship"),
            ("Prefers short, direct messages", "preference"),
            ("Birthday is March 15", "context"),
            ("From Tampines, commutes to NUS", "context"),
        ]
        for fact_text, cat in facts:
            session.add(MemoryFact(
                id=generate_uuid(), user_id=TEST_USER_ID,
                fact=fact_text, category=cat, confidence=0.85,
            ))

        # ── Tasks ────────────────────────────────────────────────
        tasks = [
            ("CS2103 Assignment 3", "pending", 3, now + timedelta(days=2), "canvas"),
            ("MA2001 Tutorial 5", "pending", 2, now + timedelta(days=1), "canvas"),
            ("Buy groceries", "pending", 1, None, "manual"),
            ("Submit IS1108 reflection", "completed", 2, now - timedelta(days=1), "manual"),
        ]
        for title, status, priority, due, source in tasks:
            session.add(Task(
                id=generate_uuid(), user_id=TEST_USER_ID,
                title=title, status=status, priority=priority,
                due_date=due, source=source,
            ))

        # ── Moods ────────────────────────────────────────────────
        moods = [(6, now - timedelta(days=3)), (5, now - timedelta(days=2)),
                 (4, now - timedelta(days=1)), (6, now - timedelta(hours=8))]
        for score, ts in moods:
            session.add(MoodLog(
                id=generate_uuid(), user_id=TEST_USER_ID,
                score=score, source="manual", created_at=ts,
            ))

        # ── Habits ───────────────────────────────────────────────
        session.add(Habit(
            id=generate_uuid(), user_id=TEST_USER_ID,
            name="Gym", target_frequency="daily",
            current_streak=12, longest_streak=21,
            last_logged=now - timedelta(days=1, hours=3),
        ))

        # ── Entities ─────────────────────────────────────────────
        session.add(UserEntity(
            id=generate_uuid(), user_id=TEST_USER_ID,
            entity_type="person", name="Noor", name_normalized="noor",
            metadata_={"contexts": ["ramen near PGP", "same faculty"]},
            mention_count=5, first_mentioned=now - timedelta(days=14),
            last_mentioned=now - timedelta(hours=2),
        ))
        session.add(UserEntity(
            id=generate_uuid(), user_id=TEST_USER_ID,
            entity_type="place", name="PGP ramen place", name_normalized="pgp ramen place",
            metadata_={"contexts": ["had ramen with Noor"]},
            mention_count=2, first_mentioned=now - timedelta(hours=2),
            last_mentioned=now - timedelta(hours=2),
        ))

        # ── Behaviors ────────────────────────────────────────────
        behaviors = [
            ("active_hours", {"peak_hours": [10, 14, 15, 21], "distribution": {"10": 0.2, "14": 0.25, "15": 0.2, "21": 0.15}}),
            ("message_length_pref", {"preference": "short", "avg_words": 4.2}),
            ("language_register", {"level": "very_casual", "markers": {"casual_marker_rate": 0.4, "singlish_marker_rate": 0.1}}),
            ("response_speed", {"avg": 180, "median": 120, "fast_pct": 0.7}),
        ]
        for key, value in behaviors:
            session.add(UserBehavior(
                id=generate_uuid(), user_id=TEST_USER_ID,
                behavior_key=key, value=value,
                confidence=0.8, sample_size=30,
                last_computed=now - timedelta(hours=5),
            ))

        # ── Expenses today ───────────────────────────────────────
        session.add(Expense(
            id=generate_uuid(), user_id=TEST_USER_ID,
            amount=8.50, category="food", description="ramen",
            created_at=now - timedelta(hours=2),
        ))

        await session.commit()

    _print_system(f"Seeded user: Rina ({TEST_USER_ID[:8]}...) with full data across all layers")


# ── Reactive flow (user sends message) ───────────────────────────────────
async def _send_message(text: str):
    """Run a message through the full LangGraph pipeline."""
    from agent.graph import build_graph, process_message

    graph = build_graph()
    agent = graph.compile()

    print(f"\n{C.BLUE}{C.BOLD}You:{C.RESET} {C.BLUE}{text}{C.RESET}")
    _print_system("  → ingress → classify → intent → context → tools → composer → memory")

    wa_sends.clear()
    result = await process_message(
        agent=agent,
        phone=TEST_PHONE,
        message_type="text",
        raw_input=text,
        wa_message_id="sandbox_msg_001",
    )

    if not wa_sends:
        response = result.get("response", "")
        if response:
            _print_donna(response)
        elif result.get("reaction_emoji"):
            print(f"  {C.DIM}(reacted with {result['reaction_emoji']}){C.RESET}")

    intent = result.get("intent", "?")
    tools = result.get("tools_needed", [])
    mem = result.get("memory_updates", [])
    _print_system(f"  intent={intent}  tools={tools}  memory_updates={len(mem)}")


# ── Proactive flow (Donna decides to message) ────────────────────────────
async def _run_donna(scenario: str = ""):
    """Run Donna's proactive loop, optionally injecting signals."""
    from donna.signals.base import Signal, SignalType
    from donna.brain.prefilter import prefilter_signals
    from donna.brain.context import build_context
    from donna.brain.candidates import generate_candidates
    from donna.brain.rules import score_and_filter
    from donna.brain.sender import send_proactive_message

    now = datetime.now(timezone.utc)

    # Build signals based on scenario
    signals = []
    if scenario == "deadline":
        signals = [
            Signal(type=SignalType.CANVAS_DEADLINE_APPROACHING, user_id=TEST_USER_ID,
                   data={"title": "CS2103 Assignment 3", "due_date": (now + timedelta(hours=26)).isoformat(),
                         "hours_left": 26, "course": "CS2103T"}),
            Signal(type=SignalType.CALENDAR_GAP_DETECTED, user_id=TEST_USER_ID,
                   data={"start": "15:00", "end": "18:00", "duration_hours": 3, "date": "today"}),
        ]
    elif scenario == "morning":
        signals = [
            Signal(type=SignalType.TIME_MORNING_WINDOW, user_id=TEST_USER_ID,
                   data={"_context_only": False, "hour": 9}),
            Signal(type=SignalType.CALENDAR_BUSY_DAY, user_id=TEST_USER_ID,
                   data={"event_count": 4, "events": ["CS2103 10-12", "IS1108 tutorial 3pm",
                          "MA2001 lecture 4pm", "CS2101 project meeting 7pm"]}),
            Signal(type=SignalType.TASK_DUE_TODAY, user_id=TEST_USER_ID,
                   data={"title": "MA2001 Tutorial 5", "due_date": now.isoformat()}),
        ]
    elif scenario == "mood":
        signals = [
            Signal(type=SignalType.MOOD_TREND_DOWN, user_id=TEST_USER_ID,
                   data={"current": 4, "previous": 6, "trend": "declining"}),
            Signal(type=SignalType.TIME_EVENING_WINDOW, user_id=TEST_USER_ID,
                   data={"_context_only": False, "hour": 20}),
        ]
    elif scenario == "grade":
        signals = [
            Signal(type=SignalType.CANVAS_GRADE_POSTED, user_id=TEST_USER_ID,
                   data={"course": "MA2001", "assignment": "Midterm", "score": "78/100",
                         "link": "https://canvas.nus.edu.sg/courses/123/grades"}),
        ]
    elif scenario == "email":
        signals = [
            Signal(type=SignalType.EMAIL_IMPORTANT_RECEIVED, user_id=TEST_USER_ID,
                   data={"from": "Prof Tan Wei Lin", "subject": "Updated CS2103 submission format",
                         "snippet": "Please note the submission format has changed to...",
                         "source_tag": "google"}),
        ]
    elif scenario == "habit":
        signals = [
            Signal(type=SignalType.HABIT_STREAK_AT_RISK, user_id=TEST_USER_ID,
                   data={"habit_name": "Gym", "current_streak": 12, "hours_since_last": 27}),
            Signal(type=SignalType.TIME_EVENING_WINDOW, user_id=TEST_USER_ID,
                   data={"_context_only": False, "hour": 20}),
        ]
    else:
        # Use real signal collection (internal signals only — no external APIs)
        from donna.signals.internal import collect_internal_signals
        signals = await collect_internal_signals(TEST_USER_ID, "Asia/Singapore")
        if not signals:
            _print_system("No signals detected. Try: /donna deadline, /donna morning, /donna mood")
            return

    # Compute dedup keys
    for s in signals:
        s.compute_dedup_key()

    scenario_label = scenario or "auto"
    _print_section(f"DONNA PROACTIVE LOOP ({scenario_label})", "")

    # Show signals
    print(f"  {C.BOLD}Signals ({len(signals)}):{C.RESET}")
    for s in signals:
        print(f"    • {s.type.value} — urgency={s.urgency_hint}")
        if s.data:
            for k, v in list(s.data.items())[:3]:
                if not k.startswith("_"):
                    print(f"      {k}: {v}")

    # Prefilter
    signals, should_continue, trust_info = await prefilter_signals(TEST_USER_ID, signals)
    if not should_continue:
        _print_system("  ✗ Blocked by prefilter (quiet hours / cooldown / daily cap)")
        return

    print(f"\n  {C.BOLD}Trust:{C.RESET} {trust_info}")

    # Build context
    _print_system("  Building context...")
    context = await build_context(TEST_USER_ID, signals, trust_info=trust_info)

    # Generate candidates
    _print_system("  Generating candidates via LLM...")
    candidates = await generate_candidates(context)

    if not candidates:
        _print_system("  LLM returned []. Donna stays silent. (This is often correct.)")
        return

    print(f"\n  {C.BOLD}Candidates ({len(candidates)}):{C.RESET}")
    for i, c in enumerate(candidates):
        score = c["relevance"] * 0.4 + c["timing"] * 0.35 + c["urgency"] * 0.25
        print(f"    {i+1}. [{c['category']}] score={score:.1f} (r={c['relevance']} t={c['timing']} u={c['urgency']})")
        print(f"       {C.GREEN}\"{c['message']}\"{C.RESET}")
        print(f"       action={c['action_type']}")

    # Score & filter
    approved = score_and_filter(candidates, context)

    if not approved:
        _print_system("  All candidates filtered out by scoring rules.")
        return

    print(f"\n  {C.BOLD}Approved:{C.RESET} {len(approved)} message(s)")

    # Send
    best = approved[0]
    _print_system("  Sending top message...")
    wa_sends.clear()
    await send_proactive_message(TEST_USER_ID, best)


# ── Info commands ─────────────────────────────────────────────────────────
async def _show_context():
    from donna.brain.context import build_context
    context = await build_context(TEST_USER_ID, [])
    _print_section("FULL CONTEXT", json.dumps(context, indent=2, default=str))


async def _show_snapshot():
    from donna.user_model import get_user_snapshot
    snapshot = await get_user_snapshot(TEST_USER_ID)
    _print_section("USER SNAPSHOT", json.dumps(snapshot, indent=2, default=str))


async def _show_signals():
    from donna.signals.internal import collect_internal_signals
    signals = await collect_internal_signals(TEST_USER_ID, "Asia/Singapore")
    if not signals:
        _print_section("SIGNALS", "No internal signals right now.")
        return
    lines = []
    for s in signals:
        lines.append(f"  {s.type.value} (urgency={s.urgency_hint})")
        for k, v in s.data.items():
            if not k.startswith("_"):
                lines.append(f"    {k}: {v}")
    _print_section(f"SIGNALS ({len(signals)})", "\n".join(lines))


async def _show_memory():
    from sqlalchemy import select
    async with _session_factory() as session:
        result = await session.execute(
            select(MemoryFact).where(MemoryFact.user_id == TEST_USER_ID)
        )
        facts = result.scalars().all()
    lines = []
    for f in facts:
        lines.append(f"  [{f.category}] {f.fact}  (confidence={f.confidence})")
    _print_section(f"MEMORY ({len(facts)} facts)", "\n".join(lines) or "  (empty)")


async def _show_behaviors():
    from sqlalchemy import select
    async with _session_factory() as session:
        result = await session.execute(
            select(UserBehavior).where(UserBehavior.user_id == TEST_USER_ID)
        )
        behaviors = result.scalars().all()
    lines = []
    for b in behaviors:
        lines.append(f"  {b.behavior_key}: {json.dumps(b.value)}")
    _print_section(f"BEHAVIORS ({len(behaviors)})", "\n".join(lines) or "  (empty)")


async def _show_history():
    from sqlalchemy import select
    async with _session_factory() as session:
        result = await session.execute(
            select(ChatMessage).where(ChatMessage.user_id == TEST_USER_ID)
            .order_by(ChatMessage.created_at.desc()).limit(20)
        )
        messages = list(reversed(result.scalars().all()))
    lines = []
    for m in messages:
        prefix = f"{C.BLUE}You" if m.role == "user" else f"{C.GREEN}Donna"
        lines.append(f"  {prefix}{C.RESET}: {m.content}")
    _print_section("CHAT HISTORY", "\n".join(lines) or "  (empty)")


# ── REPL ─────────────────────────────────────────────────────────────────
async def _repl():
    print(f"""
{C.BOLD}{'='*60}
  AURA E2E SANDBOX
  All 4 layers — real LLM, in-memory DB, mocked WhatsApp
{'='*60}{C.RESET}

{C.CYAN}You are Rina, a Y2 CS student at NUS.{C.RESET}
Type messages as Rina, or use commands:

  {C.YELLOW}/donna [scenario]{C.RESET}  — Trigger proactive loop
    scenarios: deadline, morning, mood, grade, email, habit
  {C.YELLOW}/context{C.RESET}          — Show full Donna context
  {C.YELLOW}/snapshot{C.RESET}         — Show user model snapshot
  {C.YELLOW}/signals{C.RESET}          — Show current internal signals
  {C.YELLOW}/memory{C.RESET}           — Show memory facts
  {C.YELLOW}/behaviors{C.RESET}        — Show behavioral model
  {C.YELLOW}/history{C.RESET}          — Show chat history
  {C.YELLOW}/reset{C.RESET}            — Reset DB and re-seed
  {C.YELLOW}/quit{C.RESET}             — Exit
""")

    while True:
        try:
            user_input = input(f"{C.BLUE}rina>{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input == "/quit":
            break
        elif user_input == "/reset":
            await _engine.dispose()
            await _setup_db()
            _patch_all()
            await _seed_data()
        elif user_input.startswith("/donna"):
            parts = user_input.split(maxsplit=1)
            scenario = parts[1].strip() if len(parts) > 1 else ""
            await _run_donna(scenario)
        elif user_input == "/context":
            await _show_context()
        elif user_input == "/snapshot":
            await _show_snapshot()
        elif user_input == "/signals":
            await _show_signals()
        elif user_input == "/memory":
            await _show_memory()
        elif user_input == "/behaviors":
            await _show_behaviors()
        elif user_input == "/history":
            await _show_history()
        elif user_input.startswith("/"):
            _print_system(f"Unknown command: {user_input}")
        else:
            await _send_message(user_input)


# ── Main ─────────────────────────────────────────────────────────────────
async def main():
    await _setup_db()
    _patch_all()
    await _seed_data()
    await _repl()

    # Cleanup
    for p in _patches:
        p.stop()
    await _engine.dispose()
    print(f"\n{C.DIM}Sandbox closed.{C.RESET}")


if __name__ == "__main__":
    asyncio.run(main())
