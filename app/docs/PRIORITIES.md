# Aura Reactive System — Top 3 Priorities

*Post-audit, February 2026*

---

## 1. Decompose the classifier into intent + ReAct planner loop

**Files:** `agent/nodes/classifier.py`, `agent/graph.py`, new `agent/nodes/planner.py`
**Impact:** This is the single change that turns Donna from a one-shot responder into a reasoning agent.

### The problem

The current `intent_classifier` asks one LLM call to simultaneously: classify intent (7 categories), extract entities (dates, people, amounts, topics), and predict which tools to call (from 16 available tools). It does this with zero conversation history — just the raw message text.

This breaks in three ways:

1. **Tool selection is fragile.** "What's my schedule tomorrow and are any assignments due?" requires predicting both `get_calendar_events` and `canvas_assignments` upfront. If the classifier misses one, the composer works with incomplete data and the user gets a half-answer.

2. **No iterative reasoning.** If the first tool call reveals the user needs something else (e.g., they ask about a deadline → tool returns the assignment → they'd benefit from seeing their calendar gaps too), the system can't adapt. It's one shot, done.

3. **No conversation context.** The classifier sees only the current message. "What about tomorrow?" after discussing calendar events should resolve to `get_calendar_events` for tomorrow, but without history it's unresolvable. The user has to repeat themselves.

### Target architecture

```
Current:
  classifier(intent + entities + tools) → context_loader(everything) → executor(all tools at once) → composer

Target:
  classifier(intent + entities only, WITH last 3 messages) → thin_context → planner loop → composer
```

The planner is a ReAct-style node that LangGraph routes back to itself:

```
planner:
  ├── Given: intent, entities, conversation history, minimal context
  ├── Think: what do I need to answer this?
  ├── Act: call ONE tool
  ├── Observe: what did I learn? is this enough?
  ├── Loop back if more info needed (max 3 iterations)
  └── Exit to composer when ready
```

### Implementation sketch

**Step 1:** Strip tool selection from the classifier. It only returns intent + entities now. Pass the last 3 conversation messages into the classification prompt so it can resolve references like "what about tomorrow?" or "and the other one?".

**Step 2:** Create `agent/nodes/planner.py`:

```python
PLANNER_PROMPT = """You are Donna's reasoning engine. You have the user's message,
their intent, extracted entities, and conversation history.

Decide your next action:
1. {"action": "call_tool", "tool": "tool_name", "args": {...}} — if you need information
2. {"action": "done"} — if you have enough to compose a response

What you know so far:
{accumulated_tool_results}

Available tools:
- get_calendar_events: Fetch calendar events for a date range
- canvas_assignments: Get upcoming Canvas assignments
- get_emails: Check recent emails
- get_tasks: List pending tasks
- search_memory: Search user's memory for a specific topic
- recall_context: Load a specific context slice (moods, expenses, deadlines)
[... full tool list with one-line descriptions ...]

Rules:
- Maximum 3 tool calls per turn
- Don't call tools you don't need. A greeting needs zero tools.
- If the user is venting, you probably need zero tools — just go to done.
- search_memory is your most powerful tool — use it when the user references
  something from the past that isn't in the immediate context.
"""

async def planner(state: AuraState) -> dict:
    text = state.get("transcription") or state["raw_input"]
    intent = state.get("intent", "thought")
    tool_results = state.get("tool_results", [])
    history = state.get("user_context", {}).get("conversation_history", [])[-3:]
    iterations = state.get("_planner_iterations", 0)

    # Fast-path: thoughts, vents, info_dumps, reflections skip tools entirely
    if intent in ("thought", "vent", "info_dump", "reflection") and not tool_results:
        return {"_planner_action": "done"}

    # Safety: max iterations
    if iterations >= 3:
        return {"_planner_action": "done"}

    # Build prompt with accumulated knowledge
    results_summary = json.dumps(tool_results, indent=2, default=str) if tool_results else "None yet."

    response = await llm.ainvoke([
        SystemMessage(content=PLANNER_PROMPT.format(accumulated_tool_results=results_summary)),
        HumanMessage(content=f"User: {text}\nIntent: {intent}\nEntities: {json.dumps(state.get('entities', {}))}"),
    ])

    parsed = json.loads(response.content)
    action = parsed.get("action", "done")

    if action == "call_tool":
        return {
            "_planner_action": "call_tool",
            "_next_tool": parsed["tool"],
            "_next_tool_args": parsed.get("args", {}),
            "_planner_iterations": iterations + 1,
        }

    return {"_planner_action": "done"}
```

**Step 3:** Rewire `agent/graph.py`:

```python
graph.add_node("planner", planner)

# Planner decides: call a tool or go to composer
graph.add_conditional_edges(
    "planner",
    lambda state: state.get("_planner_action", "done"),
    {
        "call_tool": "tool_executor",
        "done": "response_composer",
    },
)

# After tool execution, loop back to planner
graph.add_edge("tool_executor", "planner")

# Replace the old linear chain:
# OLD: intent_classifier → context_loader → tool_executor → response_composer
# NEW: intent_classifier → thin_context_loader → planner ⟲ tool_executor → response_composer
graph.add_edge("intent_classifier", "thin_context_loader")
graph.add_edge("thin_context_loader", "planner")
graph.add_edge("response_composer", "memory_writer")
```

**Step 4:** Modify `tool_executor` to execute a single tool per call (from `_next_tool`) instead of iterating through a list. The planner controls sequencing now.

### Why this matters

This is the architecture LangGraph was literally built for. You're currently using it as a linear chain (`A → B → C → D`), but the power is in cycles (`A → B → C → B → C → D`). The planner loop is what turns Donna from a one-shot responder into a reasoning agent that can handle "what's my schedule tomorrow and do I have anything due?" as naturally as "hey".

---

## 2. On-demand context loading instead of dump-everything

**Files:** `agent/nodes/context.py`, new tool functions in `tools/`
**Impact:** Cuts token waste by ~60% on simple messages, provides richer context for complex ones.

### The problem

Every single message — including "thanks!", "lol", "ok" — triggers `context_loader` which loads: 20 pending tasks, 7 days of mood logs, today's expenses, 10 conversation history messages, 3 deferred insights, the full user snapshot (profile, entities, behaviors, memory facts), connected integrations, upcoming deadlines, and connection instructions. That's roughly 2000 tokens of context dumped into the composer prompt regardless of whether any of it is relevant.

Meanwhile, when the user asks something that actually needs deep context — "help me plan my study schedule considering my mood this week and what's due" — the fixed context window might not have the right information loaded.

### Target architecture

Split context loading into two tiers:

**Tier 1 — Always loaded (thin_context_loader):**
```python
async def thin_context_loader(state: AuraState) -> dict:
    """Load only what every message needs. ~300 tokens."""
    user_id = state["user_id"]

    snapshot = await get_user_snapshot(user_id)  # already cached
    connected = await get_connected_integrations(user_id)

    # Last 3 messages only (not 10)
    async with async_session() as session:
        history = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(6)  # 3 turns = 6 messages
        )
        history_rows = history.scalars().all()

    context = {
        "user_profile": snapshot.get("profile", {}),
        "user_behaviors": snapshot.get("behaviors", {}),
        "connected_integrations": connected,
        "conversation_history": [
            {"role": m.role, "content": m.content}
            for m in reversed(history_rows)
        ],
    }
    return {"user_context": context}
```

**Tier 2 — On-demand via planner tool calls:**

Add a `recall_context` tool to the TOOL_REGISTRY that the planner can invoke:

```python
async def recall_context(user_id: str, entities: dict = None, **kwargs) -> dict:
    """Load a specific context slice on demand."""
    aspect = (entities or {}).get("aspect", "general")

    async with async_session() as session:
        if aspect == "tasks":
            result = await session.execute(
                select(Task).where(Task.user_id == user_id, Task.status == "pending")
                .order_by(Task.due_date.asc().nullslast()).limit(20)
            )
            return [{"title": t.title, "due": t.due_date.isoformat() if t.due_date else None,
                      "priority": t.priority} for t in result.scalars().all()]

        elif aspect == "moods":
            cutoff = datetime.utcnow() - timedelta(days=7)
            result = await session.execute(
                select(MoodLog).where(MoodLog.user_id == user_id, MoodLog.created_at >= cutoff)
                .order_by(MoodLog.created_at.desc())
            )
            return [{"score": m.score, "note": m.note, "date": m.created_at.isoformat()}
                    for m in result.scalars().all()]

        elif aspect == "deadlines":
            cutoff = datetime.utcnow() + timedelta(days=7)
            result = await session.execute(
                select(Task).where(Task.user_id == user_id, Task.status == "pending",
                                   Task.due_date.isnot(None), Task.due_date <= cutoff)
                .order_by(Task.due_date.asc())
            )
            return [{"title": t.title, "due": t.due_date.isoformat(), "source": t.source}
                    for t in result.scalars().all()]

        elif aspect == "expenses":
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            result = await session.execute(
                select(Expense).where(Expense.user_id == user_id, Expense.created_at >= today)
            )
            expenses = result.scalars().all()
            return {"today_total": sum(e.amount for e in expenses),
                    "items": [{"amount": e.amount, "category": e.category, "desc": e.description}
                              for e in expenses]}

        elif aspect == "memories":
            query = (entities or {}).get("query", "")
            # Delegate to existing search_memory tool
            from tools.memory_search import search_memory
            return await search_memory(user_id=user_id, entities={"query": query})

        elif aspect == "deferred_insights":
            result = await session.execute(
                select(DeferredInsight).where(
                    DeferredInsight.user_id == user_id,
                    DeferredInsight.used.is_(False),
                    DeferredInsight.expires_at >= datetime.utcnow(),
                ).order_by(DeferredInsight.relevance_score.desc()).limit(3)
            )
            insights = result.scalars().all()
            for d in insights:
                d.used = True
            await session.commit()
            return [{"message": d.message_draft, "category": d.category} for d in insights]

    return {}
```

Then register it:

```python
TOOL_REGISTRY["recall_context"] = recall_context
```

### The flow in practice

**User says "hey":**
- Classifier: intent=thought, no entities
- Thin context loads: profile, last 3 messages, behaviors (~300 tokens)
- Planner: thought intent → skip tools → straight to composer
- Composer gets a lean 300-token context, responds naturally

**User says "what assignments do I have due this week?":**
- Classifier: intent=question, entities={topics: ["assignments"], dates: ["this week"]}
- Thin context loads: profile, last 3 messages, behaviors (~300 tokens)
- Planner iteration 1: calls `canvas_assignments`
- Planner iteration 2: calls `recall_context(aspect="deadlines")` to cross-reference tasks
- Planner: done → composer gets exactly the context it needs

**User says "help me plan my study schedule":**
- Classifier: intent=command, entities={topics: ["study schedule"]}
- Planner iteration 1: calls `get_calendar_events` (what's the week look like?)
- Planner iteration 2: calls `canvas_assignments` (what's due?)
- Planner iteration 3: calls `recall_context(aspect="tasks")` (any manual tasks too?)
- Planner: done → composer has calendar + assignments + tasks, generates a real plan

### Why this matters

The planner loop (Priority #1) and on-demand context (Priority #2) are two sides of the same coin. The planner decides what to fetch; on-demand context gives it the tools to fetch it. Together they replace a dumb "load everything, hope the LLM finds what's useful" pattern with an intelligent "figure out what you need, go get it" pattern. This is the MemGPT insight applied to your existing architecture — self-directed context management without rewriting the system.

---

## 3. Pass conversation history into the classifier for multi-turn coherence

**File:** `agent/nodes/classifier.py`
**Impact:** Fixes the most common failure mode users will notice — Donna forgetting what you just talked about.

### The problem

The `intent_classifier` receives only `state["raw_input"]` — the current message in isolation. No conversation history. This means every message is classified in a vacuum.

Real conversations are referential:

| Turn | Message | What user means | What classifier sees |
|------|---------|-----------------|---------------------|
| 1 | "What's on my calendar tomorrow?" | Calendar query | ✅ Classifies correctly |
| 2 | "And any assignments due?" | Canvas assignments for same timeframe | ❌ No context about "same timeframe" |
| 3 | "Push the 2pm meeting to 3" | Modify the calendar event from turn 1 | ❌ No idea which meeting |
| 4 | "Thanks, what about Friday?" | Calendar query for Friday | ❌ "What about" is unresolvable |

Without history, the classifier can't resolve pronouns ("the other one"), temporal references ("and tomorrow?"), topic continuations ("what about assignments?"), or corrections ("no, I meant the CS2103 one").

### Fix

Pass the last 3 conversation messages into the classification prompt:

```python
CLASSIFICATION_PROMPT = """You are classifying a WhatsApp message from the user.

Recent conversation for context:
{history}

Current message to classify:
{message}

Return JSON only:
{{
  "intent": "task" | "question" | "thought" | "info_dump" | "vent" | "command" | "reflection",
  "entities": {{
    "dates": [],
    "people": [],
    "amounts": [],
    "topics": []
  }}
}}

Use the conversation history to resolve references:
- "what about tomorrow?" after a calendar discussion → intent: question, topics: ["calendar"]
- "and assignments?" after discussing schedule → intent: question, topics: ["assignments"]
- "the 2pm one" → resolve to the specific event/task from history
- "thanks" after getting help → intent: thought (not question)

Intent definitions:
[... same as current ...]"""


async def intent_classifier(state: AuraState) -> dict:
    text = state.get("transcription") or state["raw_input"]
    if not text:
        return {"intent": "thought", "entities": {...}, "tools_needed": []}

    # Pull last 3 conversation turns from context
    history = state.get("user_context", {}).get("conversation_history", [])[-6:]
    history_text = ""
    if history:
        lines = []
        for msg in history:
            prefix = "User" if msg["role"] == "user" else "Donna"
            lines.append(f"{prefix}: {msg['content']}")
        history_text = "\n".join(lines)
    else:
        history_text = "(no recent conversation)"

    prompt = CLASSIFICATION_PROMPT.format(history=history_text, message=text)

    response = await llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=text),
    ])

    parsed = json.loads(response.content)
    return {
        "intent": parsed.get("intent", "thought"),
        "entities": parsed.get("entities", {}),
        "tools_needed": [],  # planner handles tool selection now
    }
```

### Dependency note

This requires the `thin_context_loader` from Priority #2 to run *before* the classifier, or at minimum the conversation history to be loaded in `message_ingress`. The simplest approach: load just the last 6 ChatMessage rows in `message_ingress` and put them in `state["user_context"]["conversation_history"]` so the classifier has them immediately.

### Why this is #3

Priorities #1 and #2 make Donna smarter at deciding what to do. This one makes her smarter at understanding what was asked. A planner that reasons iteratively but misunderstands "what about Friday?" is still going to produce a bad answer. History-aware classification is the foundation that #1 and #2 build on — but it's listed third because it's the smallest code change (modify one prompt, add one query) whereas #1 and #2 are architectural shifts that deliver more total impact.

### Implementation order

Despite the numbering, you should implement these in reverse dependency order:

```
Step 1: Load conversation history in ingress (enables #3)
Step 2: History-aware classifier (#3)
Step 3: Thin context loader (#2)
Step 4: Planner loop + rewire graph (#1)
Step 5: recall_context tool + tool_executor single-tool mode (#2)
```

Each step is independently deployable and improves the system on its own. You don't have to ship all three at once.
