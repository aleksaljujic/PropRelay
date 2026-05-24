"""Build landlord approval package from diagnosis."""
from __future__ import annotations

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.services.ticket_service import get_ticket, set_ticket_status, sync_conversation_state
from app.schemas.llm_outputs import ApprovalSummary

logger = structlog.get_logger(__name__)


async def prepare_approval(state: GraphState) -> dict:
    """
    Single step: mark ticket awaiting_landlord and build approval summary.

    No messaging here — notify_landlord handles outbound communication.
    """
    ctx = get_node_context()
    db = ctx.db

    diagnosis = state.get("diagnosis") or "No diagnosis available"
    ai_json = state.get("ai_diagnosis_json") or {}
    cost_min = ai_json.get("estimated_cost_min")
    cost_max = ai_json.get("estimated_cost_max")
    if cost_min and cost_max:
        estimated = f"€{cost_min}–€{cost_max}"
    else:
        estimated = "TBD"

    summary = ApprovalSummary(
        ticket_id=state.get("ticket_id") or "",
        tenant_name=state.get("tenant_name", ""),
        unit_number=state.get("unit_number", ""),
        building_name=state.get("building_name", ""),
        category=state.get("category") or "unknown",
        urgency=state.get("urgency") or "medium",
        diagnosis=diagnosis,
        root_cause=ai_json.get("root_cause"),
        safety_risk=ai_json.get("safety_risk") or "none",
        safety_notes=ai_json.get("safety_notes"),
        estimated_cost=estimated,
        estimated_duration_minutes=ai_json.get("estimated_duration_minutes"),
        parts_needed=ai_json.get("parts_needed") or [],
        tools_needed=ai_json.get("tools_needed") or [],
        recommended_action="Approve professional dispatch",
    )

    if state.get("ticket_id"):
        ticket = await get_ticket(db, state["ticket_id"])
        if ticket:
            await set_ticket_status(db, ticket, TicketStatus.awaiting_landlord)

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="prepare_approval",
        ticket_id=state.get("ticket_id"),
        context={"approval_summary": summary.model_dump()},
    )

    logger.info("Approval package prepared", ticket_id=state.get("ticket_id"))
    return {
        "current_node": "prepare_approval",
        "context": {"approval_summary": summary.model_dump()},
    }
