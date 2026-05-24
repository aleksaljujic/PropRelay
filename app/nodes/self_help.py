"""Send self-help instructions for minor issues — terminal node."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.services.ticket_service import get_ticket, set_ticket_status, sync_conversation_state
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)


async def self_help(state: GraphState) -> dict:
    """One step: deliver self-help guidance and close the ticket."""
    ctx = get_node_context()
    db = ctx.db
    phone = state["phone"]

    steps = state.get("context", {}).get("self_help_steps") or [
        "Try the basic fix described in our guide.",
        "If the issue persists, message us again with a new photo.",
    ]
    body = "Good news — this looks like a minor issue you may be able to fix:\n\n"
    body += "\n".join(f"• {s}" for s in steps)

    await send_text_message(phone, body)

    if state.get("ticket_id"):
        ticket = await get_ticket(db, state["ticket_id"])
        if ticket:
            await set_ticket_status(
                db,
                ticket,
                TicketStatus.self_resolved,
                resolved_at=datetime.now(timezone.utc),
            )

    await sync_conversation_state(
        db,
        phone=phone,
        role=ConversationRole.tenant,
        state="completed",
        ticket_id=state.get("ticket_id"),
    )

    logger.info("Self-help delivered", ticket_id=state.get("ticket_id"))
    return {"current_node": "self_help", "completed": True, "awaiting": None}
