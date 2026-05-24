"""Dispatch selected contractor and notify tenant — one-shot, no extra YES prompts."""
from __future__ import annotations

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.services.ai_service import translate_message
from app.services.ticket_service import get_ticket, set_ticket_status, sync_conversation_state
from app.services.whatsapp import forward_image_with_caption, send_text_message

logger = structlog.get_logger(__name__)


def _resolve_media_id(state: GraphState) -> tuple[str | None, str]:
    media_id = state.get("media_id")
    media_mime = state.get("media_mime") or "image/jpeg"
    if media_id:
        return media_id, media_mime
    for ref in state.get("media_urls") or []:
        if isinstance(ref, str) and ref.startswith("meta://"):
            return ref.replace("meta://", "", 1), media_mime
    return None, media_mime


def _build_work_order(state: GraphState, contractor_name: str) -> str:
    summary = state.get("context", {}).get("approval_summary") or {}
    parts = summary.get("parts_needed") or []
    parts_line = ", ".join(parts) if parts else "TBD on inspection"
    ticket_ref = (state.get("ticket_id") or "")[:8].upper()
    return (
        f"📋 *WORK ORDER #{ticket_ref or 'NEW'}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Contractor:* {contractor_name}\n"
        f"*Building:* {state.get('building_name', '')}\n"
        f"*Unit:* {state.get('unit_number', '?')}\n"
        f"*Tenant:* {state.get('tenant_name', '')}\n\n"
        f"*Issue:*\n{state.get('diagnosis', 'See attached photo')}\n\n"
        f"*Urgency:* {(state.get('urgency') or 'medium').upper()}\n"
        f"*Category:* {(state.get('category') or 'general').upper()}\n"
        f"*Parts:* {parts_line}\n\n"
        f"Please contact the tenant to schedule the visit.\n"
        f"No reply needed — this job is assigned to you."
    )


async def _contractor_already_notified(db, ticket_id: str | None) -> bool:
    if not ticket_id:
        return False
    ticket = await get_ticket(db, ticket_id)
    if not ticket:
        return False
    return ticket.status in (TicketStatus.dispatched, TicketStatus.scheduled)


async def dispatch_contractor(state: GraphState) -> dict:
    """Notify contractor with work order + photo, notify tenant, complete workflow."""
    ctx = get_node_context()
    db = ctx.db

    if await _contractor_already_notified(db, state.get("ticket_id")):
        logger.info("Contractor dispatch already sent — completing workflow", ticket_id=state.get("ticket_id"))
        return {"current_node": "dispatch_contractor", "completed": True, "awaiting": None}

    contractor_phone = state.get("contractor_phone")
    contractor_name = state.get("contractor_name") or "our contractor"
    tenant_phone = state["phone"]
    media_id, media_mime = _resolve_media_id(state)

    if contractor_phone:
        contractor_language = state.get("context", {}).get("contractor_language", "en")
        work_order = state.get("contractor_message") or _build_work_order(state, contractor_name)
        if not state.get("contractor_message"):
            work_order = await translate_message(work_order, contractor_language)

        if media_id:
            try:
                await forward_image_with_caption(
                    contractor_phone,
                    media_id,
                    caption="Tenant photo — see work order below",
                    mime_type=media_mime,
                )
            except Exception as exc:
                logger.warning("Photo forward to contractor failed", error=str(exc))

        await send_text_message(contractor_phone, work_order)

    tenant_language = state.get("language") or "en"
    phone_hint = f" ({contractor_phone})" if contractor_phone else ""
    tenant_confirmation = await translate_message(
        f"✅ Approved! *{contractor_name}*{phone_hint} has been called and will contact you shortly.",
        tenant_language,
    )
    await send_text_message(tenant_phone, tenant_confirmation)

    if state.get("ticket_id"):
        ticket = await get_ticket(db, state["ticket_id"])
        if ticket:
            await set_ticket_status(db, ticket, TicketStatus.dispatched)

    await sync_conversation_state(
        db,
        phone=tenant_phone,
        role=ConversationRole.tenant,
        state="completed",
        ticket_id=state.get("ticket_id"),
    )

    logger.info("Contractor dispatched — workflow complete", ticket_id=state.get("ticket_id"))
    return {
        "current_node": "dispatch_contractor",
        "completed": True,
        "awaiting": None,
        "contractor_phone": contractor_phone,
        "landlord_phone": state.get("landlord_phone"),
    }
