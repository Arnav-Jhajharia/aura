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

    # Processing
    transcription: Optional[str]
    intent: Optional[str]  # task | question | thought | vent | command | reflection
    entities: dict  # extracted names, dates, amounts, topics
    tools_needed: list[str]

    # Context & results
    user_context: dict  # schedule, mood, tasks, deadlines from DB
    tool_results: list[dict]

    # Onboarding
    onboarding_step: Optional[str]   # None | awaiting_name | awaiting_timezone | awaiting_schedule | complete
    pending_action: Optional[str]    # awaiting_canvas_token | awaiting_google_token

    # Output
    response: Optional[str]
    messages: Annotated[list, add_messages]
    memory_updates: list[dict]  # new facts to persist about the user

    # Routing (internal)
    handoff_to_main: Optional[bool]  # token_collector → intent_classifier when user says something else
