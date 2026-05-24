"""Notify tenant of landlord rejection — terminal node."""
from __future__ import annotations

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.services.ticket_service import get_ticket, set_ticket_status, sync_conversation_state
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)


async def notify_rejection(state: GraphState) -> dict:
    ctx = get_node_context()
    db = ctx.db

    await send_text_message(
        state["phone"],
        "Your landlord has declined this maintenance request at this time. "
        "Please contact them directly if you have questions.",
    )

    if state.get("ticket_id"):
        ticket = await get_ticket(db, state["ticket_id"])
        if ticket:
            await set_ticket_status(db, ticket, TicketStatus.rejected, landlord_approval=False)

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="completed",
        ticket_id=state.get("ticket_id"),
    )

    logger.info("Rejection notified", ticket_id=state.get("ticket_id"))
    return {"current_node": "notify_rejection", "completed": True}
