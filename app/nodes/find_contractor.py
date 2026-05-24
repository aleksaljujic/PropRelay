"""Select contractor from landlord roster by specialty."""
from __future__ import annotations

import uuid

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.services.contractor_selection import contractor_ids, select_contractor_candidates
from app.services.ticket_service import get_ticket, set_ticket_status, sync_conversation_state
from app.storage.pending_routes import get_thread_contractor_recommendation

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

    # Use the contractor the landlord already saw in the approval report.
    if state.get("contractor_id") and state.get("contractor_phone"):
        selected_id = state["contractor_id"]
        candidates = state.get("contractor_candidates") or [selected_id]
        selected_name = state.get("contractor_name")
        selected_phone = state.get("contractor_phone")
        selected_language = state.get("context", {}).get("contractor_language", "en")
    else:
        rec = await get_thread_contractor_recommendation(state["thread_id"])
        if rec and rec.get("contractor_id"):
            selected_id = rec["contractor_id"]
            candidates = [selected_id]
            selected_name = rec.get("contractor_name")
            selected_phone = rec.get("contractor_phone")
            selected_language = state.get("context", {}).get("contractor_language", "en")
        else:
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
            selected_name = selected.name if selected else None
            selected_phone = selected.phone_number if selected else None
            selected_language = getattr(selected, "language", None) or "en" if selected else "en"

    if not candidates:
        logger.warning("No contractors available", specialty=specialty)
        return {"error": "no_contractors", "completed": True}

    if state.get("ticket_id"):
        ticket = await get_ticket(db, state["ticket_id"])
        if ticket:
            contractor_uuid = uuid.UUID(selected_id) if selected_id else None
            await set_ticket_status(
                db,
                ticket,
                TicketStatus.approved,
                landlord_approval=True,
                contractor_id=contractor_uuid,
            )

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="find_contractor",
        ticket_id=state.get("ticket_id"),
    )

    logger.info(
        "Contractor selected",
        contractor_id=selected_id,
        attempt=attempt,
        language=selected_language,
    )
    return {
        "current_node": "find_contractor",
        "contractor_candidates": candidates,
        "contractor_id": selected_id,
        "contractor_name": selected_name,
        "contractor_phone": selected_phone,
        "contractor_attempt": attempt,
        "context": {"contractor_language": selected_language},
    }
