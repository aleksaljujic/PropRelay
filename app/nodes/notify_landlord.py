"""
Notify landlord with diagnosis + draft contractor message.

Landlord can:
  - Reply YES → send the draft as-is
  - Reply with custom text → use that as the contractor message
  - Reply NO → reject
"""
from __future__ import annotations

import uuid

import structlog
from langgraph.types import interrupt

from app.config import settings
from app.graph.context import get_node_context
from app.storage.pending_routes import register_landlord_pending
from app.graph.state import GraphState
from app.models.ticket import ConversationRole
from app.services.contractor_selection import select_contractor_candidates
from app.services.ticket_service import sync_conversation_state
from app.services.whatsapp import send_text_message
from app.workers.timeout_scheduler import TimeoutKind, schedule_timeout

logger = structlog.get_logger(__name__)

URGENCY_EMOJI = {"emergency": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢"}
_APPROVE_WORDS = {"yes", "y", "approve", "approved", "ja", "ok", "da", "👍", "send", "send it"}
_REJECT_WORDS  = {"no", "n", "reject", "rejected", "ne", "nein", "👎"}


def _build_contractor_draft(state: GraphState, contractor_name: str) -> str:
    """Plain-text draft the landlord sees and can edit."""
    return (
        f"Hi {contractor_name},\n\n"
        f"We have a {state.get('category', 'maintenance')} issue at "
        f"*{state.get('building_name', 'our building')}*, unit *{state.get('unit_number', '?')}*.\n\n"
        f"Problem: {state.get('diagnosis', 'See attached')}\n\n"
        f"Urgency: {(state.get('urgency') or 'medium').upper()}\n\n"
        f"Please contact the tenant to arrange a visit.\n"
        f"Reply CONFIRM to accept this job."
    )


async def _build_landlord_message(state: GraphState, db) -> tuple[str, str, str | None]:
    """
    Returns (landlord_msg, contractor_draft, contractor_phone).
    """
    summary = state.get("context", {}).get("approval_summary") or {}
    urgency = summary.get("urgency") or state.get("urgency", "medium")
    category = summary.get("category") or state.get("category", "general")
    diagnosis = state.get("diagnosis") or summary.get("diagnosis", "")
    estimated = summary.get("estimated_cost", "TBD")
    emoji = URGENCY_EMOJI.get(urgency, "🟡")
    tenant_note = state.get("context", {}).get("tenant_note", "")

    # Find proposed contractor
    contractor_name = "contractor"
    contractor_phone = None
    try:
        candidates = await select_contractor_candidates(
            db, uuid.UUID(state["landlord_id"]), category
        )
        if candidates:
            contractor_name = candidates[0].name
            contractor_phone = candidates[0].phone_number
    except Exception:
        pass

    draft = _build_contractor_draft(state, contractor_name)

    tenant_note_line = f"\n📝 Tenant note: _{tenant_note}_" if tenant_note else ""

    landlord_msg = (
        f"{emoji} *Maintenance — unit {state.get('unit_number', '?')}*\n"
        f"Building: {state.get('building_name', '')}\n"
        f"Category: *{category.upper()}* | Urgency: *{urgency.upper()}*\n\n"
        f"🔍 Diagnosis: {diagnosis}{tenant_note_line}\n"
        f"💶 Est. cost: {estimated}\n\n"
        f"👷 Contractor: *{contractor_name}*"
        + (f" ({contractor_phone})" if contractor_phone else "") +
        "\n\n"
        f"─────────────────\n"
        f"*Draft message to repairman:*\n\n"
        f"{draft}\n"
        f"─────────────────\n\n"
        f"Reply:\n"
        f"• *YES* — send this draft\n"
        f"• *NO* — reject request\n"
        f"• Or type your own message to replace the draft"
    )

    return landlord_msg, draft, contractor_phone


async def notify_landlord(state: GraphState) -> dict:
    ctx = get_node_context()
    db = ctx.db

    # ── Resume path — landlord replied ───────────────────────────────────────
    resume = state.get("resume_value")
    if resume is not None:
        reply = str(resume).strip()
        lower = reply.lower()

        if lower in _REJECT_WORDS:
            logger.info("Landlord rejected", phone=state["phone"])
            return {
                "landlord_approved": False,
                "current_node": "notify_landlord",
                "resume_value": None,
            }

        # YES or custom message → approve
        original_draft = state.get("context", {}).get("contractor_draft", "")
        contractor_message = original_draft if lower in _APPROVE_WORDS else reply

        logger.info("Landlord approved", custom_message=(lower not in _APPROVE_WORDS))
        return {
            "landlord_approved": True,
            "contractor_message": contractor_message,
            "current_node": "notify_landlord",
            "resume_value": None,
        }

    # ── First pass — send to landlord ─────────────────────────────────────────
    landlord_phone = state.get("landlord_phone")
    if not landlord_phone:
        return {"error": "missing_landlord_phone"}

    landlord_msg, draft, contractor_phone = await _build_landlord_message(state, db)

    await send_text_message(landlord_phone, landlord_msg)

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

    # Persist draft so resume path can use it
    new_context = {**state.get("context", {}), "contractor_draft": draft}

    decision = interrupt({"awaiting": "landlord_approval", "ticket_id": state.get("ticket_id")})
    reply = str(decision).strip() if decision else ""
    lower = reply.lower()

    if lower in _REJECT_WORDS:
        return {"landlord_approved": False, "current_node": "notify_landlord", "context": new_context, "resume_value": None}

    contractor_message = draft if lower in _APPROVE_WORDS else reply
    return {
        "landlord_approved": True,
        "contractor_message": contractor_message,
        "current_node": "notify_landlord",
        "context": new_context,
        "resume_value": None,
    }
