import logging

from langgraph.graph import END, StateGraph

from agent.nodes.classifier import classify_type, intent_classifier, route_by_type
from agent.nodes.composer import response_composer
from agent.nodes.context import thin_context_loader
from agent.nodes.executor import tool_executor
from agent.nodes.ingress import message_ingress
from agent.nodes.memory import memory_writer
from agent.nodes.naturalizer import naturalizer
from agent.nodes.onboarding import onboarding_handler
from agent.nodes.planner import planner
from agent.nodes.token_collector import token_collector, _looks_like_canvas_token
from agent.nodes.transcriber import voice_transcriber
from agent.state import AuraState

logger = logging.getLogger(__name__)


def route_after_token_collector(state: AuraState) -> str:
    """If user said something else (not a token), hand off to main flow."""
    if state.get("handoff_to_main"):
        return "intent_classifier"
    return "naturalizer"


# ── Conversation starter button → natural text mapping ────────────────────────
STARTER_EXPANSIONS: dict[str, str] = {
    "starter_due": "What's due this week?",
    "starter_mood": "I want to log my mood",
    "starter_help": "What can you do?",
    "starter_task": "I want to add a task",
}


def _detect_connect_intent(raw: str) -> str | None:
    """Detect natural-language connection requests → pending_action key."""
    lower = raw.lower().strip()
    # Exact button payloads
    if lower in ("connect_canvas", "connect_google", "connect_microsoft"):
        return lower
    # Natural language variants
    if any(k in lower for k in ("connect google", "link google", "setup google", "set up google")):
        return "connect_google"
    if any(k in lower for k in ("connect outlook", "link outlook", "setup outlook", "set up outlook",
                                 "connect microsoft", "link microsoft")):
        return "connect_microsoft"
    if any(k in lower for k in ("connect canvas", "link canvas", "setup canvas", "set up canvas")):
        return "connect_canvas"
    return None


def route_after_ingress(state: AuraState) -> str:
    """Route message to the right handler after ingress."""
    # Expand conversation starter button IDs into natural text
    raw = state.get("raw_input", "")
    expansion = STARTER_EXPANSIONS.get(raw.strip())
    if expansion:
        state["raw_input"] = expansion
        raw = expansion

    # Pending token collection takes priority
    action = state.get("pending_action")
    if action in ("connect_canvas", "awaiting_canvas_token", "connect_google", "connect_microsoft"):
        return "token_collector"
    # Natural language connection requests
    connect_action = _detect_connect_intent(raw)
    if connect_action:
        state["pending_action"] = connect_action
        return "token_collector"
    # Auto-detect: user pasted a Canvas token without tapping the button first
    if _looks_like_canvas_token(raw):
        return "token_collector"
    if not state.get("user_context", {}).get("onboarding_complete"):
        return "onboarding_handler"
    return "classify_type"


def route_planner(state: AuraState) -> str:
    """Planner decides: call a tool and loop back, or hand off to composer."""
    action = state.get("_planner_action", "done")
    if action in ("call_tool", "call_tools"):
        return "tool_executor"
    return "response_composer"


def build_graph() -> StateGraph:
    """Construct the Aura LangGraph StateGraph.

    Architecture:
      ingress → [onboarding | token_collector | classify_type]
      classify_type → [voice_transcriber →] intent_classifier
      intent_classifier → thin_context_loader → planner ⟲ tool_executor → response_composer
      response_composer → memory_writer → END
    """
    graph = StateGraph(AuraState)

    # Add nodes
    graph.add_node("message_ingress", message_ingress)
    graph.add_node("onboarding_handler", onboarding_handler)
    graph.add_node("token_collector", token_collector)
    graph.add_node("naturalizer", naturalizer)
    graph.add_node("classify_type", classify_type)
    graph.add_node("voice_transcriber", voice_transcriber)
    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("thin_context_loader", thin_context_loader)
    graph.add_node("planner", planner)
    graph.add_node("tool_executor", tool_executor)
    graph.add_node("response_composer", response_composer)
    graph.add_node("memory_writer", memory_writer)

    # Entry: branch on onboarding status
    graph.set_entry_point("message_ingress")
    graph.add_conditional_edges(
        "message_ingress",
        route_after_ingress,
        {
            "token_collector": "token_collector",
            "onboarding_handler": "onboarding_handler",
            "classify_type": "classify_type",
        },
    )

    # Shortcut paths
    graph.add_edge("onboarding_handler", "naturalizer")
    graph.add_conditional_edges(
        "token_collector",
        route_after_token_collector,
        {
            "naturalizer": "naturalizer",
            "intent_classifier": "intent_classifier",
        },
    )
    graph.add_edge("naturalizer", "memory_writer")

    # Normal flow: conditional voice → transcriber, text → intent classifier
    graph.add_conditional_edges(
        "classify_type",
        route_by_type,
        {
            "voice": "voice_transcriber",
            "text": "intent_classifier",
        },
    )
    graph.add_edge("voice_transcriber", "intent_classifier")

    # ── ReAct planner loop ────────────────────────────────────────────
    # classifier → thin context → planner ⟲ tool_executor → composer
    graph.add_edge("intent_classifier", "thin_context_loader")
    graph.add_edge("thin_context_loader", "planner")
    graph.add_conditional_edges(
        "planner",
        route_planner,
        {
            "tool_executor": "tool_executor",
            "response_composer": "response_composer",
        },
    )
    # After tool execution, loop back to planner for next decision
    graph.add_edge("tool_executor", "planner")

    graph.add_edge("response_composer", "memory_writer")
    graph.add_edge("memory_writer", END)

    return graph


async def process_message(
    agent,
    phone: str,
    message_type: str,
    raw_input: str,
    media_id: str | None = None,
    wa_message_id: str | None = None,
    wa_profile_name: str | None = None,
):
    """Entry point: run a WhatsApp message through the agent graph."""
    initial_state: AuraState = {
        "user_id": "",
        "phone": phone,
        "message_type": message_type,
        "raw_input": raw_input,
        "media_id": media_id,
        "wa_message_id": wa_message_id,
        "wa_profile_name": wa_profile_name,
        "transcription": None,
        "intent": None,
        "entities": {},
        "tools_needed": [],
        "user_context": {},
        "tool_results": [],
        "onboarding_step": None,
        "pending_action": None,
        "response": None,
        "reaction_emoji": None,
        "messages": [],
        "memory_updates": [],
        # Planner state
        "_planner_action": None,
        "_next_tool": None,
        "_next_tool_args": None,
        "_next_tools": None,
        "_planner_iterations": 0,
        "_pending_flow": None,
    }

    config = {"configurable": {"thread_id": phone}}
    result = await agent.ainvoke(initial_state, config=config)
    logger.info("Processed message for %s — intent: %s", phone, result.get("intent"))
    return result
