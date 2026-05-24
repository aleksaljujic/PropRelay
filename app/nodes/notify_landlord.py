"""Notify landlord and pause for human approval."""
from __future__ import annotations

import structlog
from langgraph.types import interrupt

from app.config import settings
from app.graph.context import get_node_context
from app.storage.pending_routes import register_contractor_pending, register_landlord_pending
from app.graph.state import GraphState
from app.models.ticket import ConversationRole
from app.services.ticket_service import sync_conversation_state
from app.services.whatsapp import send_text_message
from app.workers.timeout_scheduler import schedule_timeout, TimeoutKind

logger = structlog.get_logger(__name__)


def _format_landlord_message(state: GraphState) -> str:
    summary = state.get("context", {}).get("approval_summary") or {}
    return (
        f"🔧 New maintenance ticket\n"
        f"Unit: {summary.get('unit_number', state.get('unit_number'))}\n"
        f"Building: {summary.get('building_name', state.get('building_name'))}\n"
        f"Category: {summary.get('category', 'unknown').upper()}\n"
        f"Urgency: {summary.get('urgency', 'medium').upper()}\n"
        f"Diagnosis: {summary.get('diagnosis', state.get('diagnosis', ''))}\n"
        f"Est. cost: {summary.get('estimated_cost', 'TBD')}\n\n"
        f"Reply YES to approve or NO to reject."
    )


async def notify_landlord(state: GraphState) -> dict:
    """
    Send approval request to landlord, schedule escalation timeout, interrupt.

    Resumes when orchestrator passes resume_value from landlord's YES/NO reply.
    """
    ctx = get_node_context()
    db = ctx.db

    # Resume path — landlord responded via interrupt resume
    resume = state.get("resume_value")
    if resume is None:
        pass  # fall through to interrupt handling below
    else:
        approved = _parse_approval(resume)
        logger.info("Landlord decision received", approved=approved)
        return {
            "landlord_approved": approved,
            "current_node": "notify_landlord",
            "awaiting": None,
            "resume_value": None,
        }

    landlord_phone = state.get("landlord_phone")
    if not landlord_phone:
        return {"error": "missing_landlord_phone"}

    await send_text_message(landlord_phone, _format_landlord_message(state))

    await schedule_timeout(
        kind=TimeoutKind.LANDLORD_ESCALATION,
        thread_id=state["thread_id"],
        ticket_id=state.get("ticket_id") or "",
        phone=state["phone"],
        landlord_phone=landlord_phone,
        delay_seconds=settings.timeout_landlord_escalation_seconds,
    )

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="notify_landlord",
        ticket_id=state.get("ticket_id"),
        context={"awaiting": "landlord_approval"},
    )

    await register_landlord_pending(landlord_phone, state["thread_id"])

    decision = interrupt({"awaiting": "landlord_approval", "ticket_id": state.get("ticket_id")})
    approved = _parse_approval(decision)
    return {
        "landlord_approved": approved,
        "current_node": "notify_landlord",
        "awaiting": None,
    }


def _parse_approval(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"yes", "y", "approve", "approved", "ja", "ok", "👍"}
