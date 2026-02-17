from typing import Annotated, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages


class AuraState(TypedDict):
    # Identifiers
    user_id: str
    phone: str

    # Input
    message_type: Literal["text", "voice", "image", "location"]
    raw_input: str
    media_id: Optional[str]
    wa_message_id: Optional[str]  # WhatsApp message ID (for reactions)
    wa_profile_name: Optional[str]  # WhatsApp profile display name

    # Processing
    transcription: Optional[str]
    intent: Optional[str]  # task | question | capabilities | thought | vent | command | reflection | info_dump
    entities: dict  # extracted names, dates, amounts, topics
    tools_needed: list[str]

    # Context & results
    user_context: dict  # schedule, mood, tasks, deadlines from DB
    tool_results: list[dict]

    # Onboarding
    onboarding_step: Optional[str]   # None | awaiting_name | awaiting_tz_confirm | awaiting_timezone | awaiting_schedule | complete
    pending_action: Optional[str]    # awaiting_canvas_token | awaiting_google_token

    # Output
    response: Optional[str]
    reaction_emoji: Optional[str]    # If set, react to user's message instead of/alongside text reply
    messages: Annotated[list, add_messages]
    memory_updates: list[dict]  # new facts to persist about the user

    # Planner (internal)
    _planner_action: Optional[str]       # "call_tool" | "done"
    _next_tool: Optional[str]            # single tool name for planner-driven execution
    _next_tool_args: Optional[dict]      # args for _next_tool
    _planner_iterations: int             # ReAct loop counter (max 3)

    # Routing (internal)
    handoff_to_main: Optional[bool]  # token_collector → intent_classifier when user says something else
