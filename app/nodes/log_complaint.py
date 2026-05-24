"""Log non-maintenance complaints — terminal branch."""
from __future__ import annotations

import uuid

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.tenant import Tenant
from app.models.ticket import ConversationRole, TicketCategory, TicketStatus
from app.services.ticket_service import create_ticket, set_ticket_status, sync_conversation_state
from app.services.whatsapp import send_text_message
from sqlalchemy import select

logger = structlog.get_logger(__name__)


async def log_complaint(state: GraphState) -> dict:
    ctx = get_node_context()
    db = ctx.db

    text = state.get("message_text") or ""
    tenant = await db.scalar(
        select(Tenant).where(Tenant.id == uuid.UUID(state["tenant_id"]))
    )

    if tenant and not state.get("ticket_id"):
        ticket = await create_ticket(
            db,
            tenant,
            description=text,
            category=TicketCategory.complaint.value,
            urgency="low",
        )
        await set_ticket_status(db, ticket, TicketStatus.triaged)
        ticket_id = str(ticket.id)
    else:
        ticket_id = state.get("ticket_id")

    await send_text_message(
        state["phone"],
        "Thank you — your complaint has been logged and forwarded to your landlord.",
    )

    landlord_phone = state.get("landlord_phone")
    if landlord_phone:
        await send_text_message(
            landlord_phone,
            f"📝 Complaint from {state.get('tenant_name')} (unit {state.get('unit_number')}):\n{text}",
        )

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="completed",
        ticket_id=ticket_id,
    )

    logger.info("Complaint logged", ticket_id=ticket_id)
    return {"current_node": "log_complaint", "completed": True, "ticket_id": ticket_id}
