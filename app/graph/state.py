"""
Typed state definition for the maintenance orchestration graph.

State is persisted in Redis via the checkpoint saver and mirrored to
conversation_states in PostgreSQL for crash recovery.
"""
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


def merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Reducer: shallow-merge context dicts across node updates."""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class GraphState(TypedDict, total=False):
    """
    Shared state passed between LangGraph nodes.

    Each node reads what it needs and returns a partial update.
    Never block inside a node — use interrupt() for human-in-the-loop.
    """

    # ── Identity ──────────────────────────────────────────────────────────
    thread_id: str  # Redis checkpoint key (tenant phone)
    phone: str
    tenant_id: str
    tenant_name: str
    unit_number: str
    building_id: str
    building_name: str
    landlord_id: str
    landlord_phone: str
    language: str

    # ── Current inbound message ───────────────────────────────────────────
    message_id: str
    message_type: str  # text | image | ...
    message_text: str
    media_id: str | None
    media_mime: str | None

    # ── Workflow control ──────────────────────────────────────────────────
    intent: Literal["maintenance", "complaint", "admin"] | None
    current_node: str | None
    severity: Literal["minor", "serious"] | None
    awaiting: str | None  # photo | landlord_approval | contractor_confirm
    resume_value: Any | None  # payload from next human message

    # ── Ticket / diagnosis ────────────────────────────────────────────────
    ticket_id: str | None
    category: str | None
    urgency: str | None
    diagnosis: str | None
    ai_diagnosis_json: dict[str, Any] | None
    media_urls: list[str]

    # ── Approval / dispatch ───────────────────────────────────────────────
    landlord_approved: bool | None
    contractor_id: str | None
    contractor_name: str | None
    contractor_phone: str | None
    contractor_candidates: list[str]  # ordered contractor UUID strings
    contractor_attempt: int

    # ── Audit / errors ────────────────────────────────────────────────────
    messages: Annotated[list[Any], add_messages]
    context: Annotated[dict[str, Any], merge_dicts]
    error: str | None
    completed: bool
