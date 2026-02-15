import logging

from langgraph.graph import END, StateGraph

from agent.nodes.classifier import classify_type, intent_classifier, route_by_type
from agent.nodes.composer import response_composer
from agent.nodes.context import context_loader
from agent.nodes.executor import tool_executor
from agent.nodes.ingress import message_ingress
from agent.nodes.memory import memory_writer
from agent.nodes.naturalizer import naturalizer
from agent.nodes.onboarding import onboarding_handler
from agent.nodes.token_collector import token_collector, _looks_like_canvas_token
from agent.nodes.transcriber import voice_transcriber
from agent.state import AuraState

logger = logging.getLogger(__name__)


def route_after_token_collector(state: AuraState) -> str:
    """If user said something else (not a token), hand off to main flow."""
    if state.get("handoff_to_main"):
        return "intent_classifier"
    return "naturalizer"


def route_after_ingress(state: AuraState) -> str:
    """Route message to the right handler after ingress."""
    # Pending token collection takes priority
    action = state.get("pending_action")
    raw = state.get("raw_input", "")
    if action in ("connect_canvas", "awaiting_canvas_token", "connect_google") or \
       raw in ("connect_canvas", "connect_google"):
        return "token_collector"
    # Auto-detect: user pasted a Canvas token without tapping the button first
    if _looks_like_canvas_token(raw):
        return "token_collector"
    if not state.get("user_context", {}).get("onboarding_complete"):
        return "onboarding_handler"
    return "classify_type"


def build_graph() -> StateGraph:
    """Construct the Aura LangGraph StateGraph."""
    graph = StateGraph(AuraState)

    # Add nodes
    graph.add_node("message_ingress", message_ingress)
    graph.add_node("onboarding_handler", onboarding_handler)
    graph.add_node("token_collector", token_collector)
    graph.add_node("naturalizer", naturalizer)
    graph.add_node("classify_type", classify_type)
    graph.add_node("voice_transcriber", voice_transcriber)
    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("context_loader", context_loader)
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
    graph.add_edge("intent_classifier", "context_loader")
    graph.add_edge("context_loader", "tool_executor")
    graph.add_edge("tool_executor", "response_composer")
    graph.add_edge("response_composer", "memory_writer")
    graph.add_edge("memory_writer", END)

    return graph


async def process_message(
    agent,
    phone: str,
    message_type: str,
    raw_input: str,
    media_id: str | None = None,
):
    """Entry point: run a WhatsApp message through the agent graph."""
    initial_state: AuraState = {
        "user_id": "",
        "phone": phone,
        "message_type": message_type,
        "raw_input": raw_input,
        "media_id": media_id,
        "transcription": None,
        "intent": None,
        "entities": {},
        "tools_needed": [],
        "user_context": {},
        "tool_results": [],
        "onboarding_step": None,
        "pending_action": None,
        "response": None,
        "messages": [],
        "memory_updates": [],
    }

    config = {"configurable": {"thread_id": phone}}
    result = await agent.ainvoke(initial_state, config=config)
    logger.info("Processed message for %s — intent: %s", phone, result.get("intent"))
    return result
