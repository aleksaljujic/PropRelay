"""Dispatch selected contractor and notify tenant."""
from __future__ import annotations

import structlog
from langgraph.types import interrupt

from app.config import settings
from app.graph.context import get_node_context
from app.storage.pending_routes import register_contractor_pending
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.services.ai_service import translate_message
from app.services.ticket_service import get_ticket, set_ticket_status, sync_conversation_state
from app.services.whatsapp import forward_image_with_caption, send_text_message
from app.workers.timeout_scheduler import schedule_timeout, TimeoutKind

logger = structlog.get_logger(__name__)


async def dispatch_contractor(state: GraphState) -> dict:
    """
    Notify contractor, schedule confirm timeout, notify tenant, complete workflow.

    Optional interrupt if contractor confirmation is required before closing.
    """
    ctx = get_node_context()
    db = ctx.db

    resume = state.get("resume_value")
    if resume is not None and str(resume).lower() in {"confirmed", "yes", "ja"}:
        return await _finalize_dispatch(state, db)

    contractor_phone = state.get("contractor_phone")
    contractor_name = state.get("contractor_name") or "our contractor"
    tenant_phone = state["phone"]

    if contractor_phone:
        contractor_language = state.get("context", {}).get("contractor_language", "en")

        contractor_msg = state.get("contractor_message") or (
            f"New job at {state.get('building_name')} unit {state.get('unit_number')}.\n"
            f"Issue: {state.get('diagnosis', 'See ticket')}.\n"
            f"Urgency: {(state.get('urgency') or 'medium').upper()}.\n"
            f"Reply CONFIRM to accept."
        )
        if not state.get("contractor_message"):
            contractor_msg = await translate_message(contractor_msg, contractor_language)

        # 1) Forward the photo first so contractor sees what they're walking into
        if state.get("media_id"):
            try:
                await forward_image_with_caption(
                    contractor_phone,
                    state["media_id"],
                    caption="",
                    mime_type=state.get("media_mime") or "image/jpeg",
                )
            except Exception as exc:
                logger.warning("Photo forward to contractor failed", error=str(exc))

        # 2) Send the job message
        await send_text_message(contractor_phone, contractor_msg)
        await register_contractor_pending(contractor_phone, state["thread_id"])
        await schedule_timeout(
            kind=TimeoutKind.CONTRACTOR_CONFIRM,
            thread_id=state["thread_id"],
            ticket_id=state.get("ticket_id") or "",
            phone=tenant_phone,
            contractor_phone=contractor_phone,
            contractor_attempt=state.get("contractor_attempt") or 0,
            delay_seconds=settings.timeout_contractor_confirm_seconds,
        )

    tenant_language = state.get("language") or "en"
    tenant_confirmation = await translate_message(
        f"✅ Approved! {contractor_name} has been notified and will contact you shortly.",
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
        state="dispatch_contractor",
        ticket_id=state.get("ticket_id"),
    )

    # Pause for contractor confirm; auto-complete if they reply CONFIRM
    confirm = interrupt({"awaiting": "contractor_confirm"})
    if confirm and str(confirm).lower() in {"confirmed", "confirm", "yes", "ja"}:
        return await _finalize_dispatch(state, db)
    return {"current_node": "dispatch_contractor", "awaiting": "contractor_confirm"}


async def _finalize_dispatch(state: GraphState, db) -> dict:
    if state.get("ticket_id"):
        ticket = await get_ticket(db, state["ticket_id"])
        if ticket:
            await set_ticket_status(db, ticket, TicketStatus.scheduled)

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="completed",
        ticket_id=state.get("ticket_id"),
    )
    logger.info("Contractor confirmed", ticket_id=state.get("ticket_id"))
    return {"current_node": "dispatch_contractor", "completed": True, "awaiting": None}
