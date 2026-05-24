"""Select contractor from landlord roster by specialty."""
from __future__ import annotations

import uuid

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.services.contractor_selection import contractor_ids, select_contractor_candidates
from app.services.ticket_service import get_ticket, set_ticket_status, sync_conversation_state

logger = structlog.get_logger(__name__)


async def find_contractor(state: GraphState) -> dict:
    """
    Pick ordered contractor candidates — no LLM involved.

    dispatch_contractor tries candidates[attempt]; timeout worker advances attempt.
    """
    ctx = get_node_context()
    db = ctx.db

    specialty = state.get("category") or "general"
    attempt = state.get("contractor_attempt") or 0

    candidates = state.get("contractor_candidates")
    if not candidates:
        contractors = await select_contractor_candidates(
            db,
            uuid.UUID(state["landlord_id"]),
            specialty,
        )
        candidates = contractor_ids(contractors)

    if not candidates:
        logger.warning("No contractors available", specialty=specialty)
        return {"error": "no_contractors", "completed": True}

    idx = min(attempt, len(candidates) - 1)
    selected_id = candidates[idx]

    contractors = await select_contractor_candidates(
        db, uuid.UUID(state["landlord_id"]), specialty
    )
    selected = next((c for c in contractors if str(c.id) == selected_id), contractors[0] if contractors else None)

    if state.get("ticket_id"):
        ticket = await get_ticket(db, state["ticket_id"])
        if ticket:
            await set_ticket_status(
                db,
                ticket,
                TicketStatus.approved,
                landlord_approval=True,
                contractor_id=selected.id if selected else None,
            )

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="find_contractor",
        ticket_id=state.get("ticket_id"),
    )

    logger.info("Contractor selected", contractor_id=selected_id, attempt=attempt)
    return {
        "current_node": "find_contractor",
        "contractor_candidates": candidates,
        "contractor_id": selected_id,
        "contractor_name": selected.name if selected else None,
        "contractor_phone": selected.phone_number if selected else None,
        "contractor_attempt": attempt,
    }
