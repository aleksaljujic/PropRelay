"""
WhatsApp Webhook — Meta Cloud API integration.

GET  /api/v1/webhook  — hub verification challenge
POST /api/v1/webhook  — incoming messages and status updates
"""
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.core.redis import get_conversation_state
from app.database import async_session_factory
from app.graph.orchestrator import lookup_landlord_by_phone, orchestrator
from app.services.landlord_commands import handle_landlord_command, handle_pending_delete_reply
from app.services.onboarding_service import (
    UNKNOWN_NUMBER_MSG,
    handle_onboarding_reply,
    initiate_tenant_onboarding,
)
from app.services.tenant_lookup import get_tenant_by_phone
from app.services.whatsapp import send_text_message
from app.models.contractor import Contractor
from sqlalchemy import select

router = APIRouter()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# GET /webhook  — Meta hub verification
# ---------------------------------------------------------------------------

@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> str:
    if hub_mode != "subscribe":
        raise HTTPException(status_code=403, detail="Invalid hub.mode")
    if hub_verify_token != settings.meta_webhook_verify_token:
        logger.warning("Webhook verification failed — bad verify_token")
        raise HTTPException(status_code=403, detail="Invalid verify token")
    logger.info("Webhook verification successful")
    return hub_challenge


# ---------------------------------------------------------------------------
# POST /webhook  — incoming messages
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Return 200 immediately; heavy processing runs in a background task."""
    payload: dict = await request.json()
    logger.debug("Raw webhook payload", payload=payload)

    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value: dict = change.get("value", {})

            for message in value.get("messages", []):
                background_tasks.add_task(_handle_incoming_message, message, value)

            for status in value.get("statuses", []):
                logger.info(
                    "Message status update",
                    message_id=status.get("id"),
                    status=status.get("status"),
                    recipient=status.get("recipient_id"),
                )

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Internal message handler
# ---------------------------------------------------------------------------

async def _handle_incoming_message(message: dict, value: dict) -> None:
    """Route an incoming WhatsApp message. Runs as a background task."""
    sender_phone: str = message.get("from", "unknown")
    msg_type: str = message.get("type", "unknown")
    message_id: str = message.get("id", "")

    text_body = ""
    if msg_type == "text":
        text_body = message.get("text", {}).get("body", "")

    log = logger.bind(phone=sender_phone, message_id=message_id, type=msg_type)
    log.info("Message received", text=text_body or f"[{msg_type}]")

    async with async_session_factory() as db:
        # ── Landlord replies (approval flow) ───────────────────────────────
        landlord = await lookup_landlord_by_phone(db, sender_phone)
        if landlord and msg_type == "text":
            # Pending tenant delete confirmation — before maintenance YES/NO
            if await handle_pending_delete_reply(landlord, text_body, db):
                log.info("Landlord delete confirmation handled", text=text_body)
                return

            # Pending maintenance approval — resume graph before command handler
            try:
                result = await orchestrator.dispatch_landlord_message(landlord, text_body, db)
                if result is not None:
                    log.info("Landlord approval routed to orchestrator")
                    return
            except Exception as exc:
                log.exception("Landlord graph resume error", error=str(exc))
                # Fall through to command handler if graph resume fails

            # No pending approval — handle as a management command
            try:
                if await handle_landlord_command(landlord, text_body, db):
                    log.info("Landlord command handled", text=text_body)
                    return
            except Exception as exc:
                log.exception("Landlord command error", error=str(exc))
                await send_text_message(
                    sender_phone,
                    "⚠️ Something went wrong processing your command.\nType *help* to see available commands.",
                )
                return

            # Unrecognised landlord message — show hint, never fall through to tenant flow
            await send_text_message(
                sender_phone,
                "Type *help* to see available commands.\n\nExample: `register 381641234567 3A`",
            )
            return

        # ── Contractor replies (confirm flow) ──────────────────────────────
        if msg_type == "text":
            contractor = await db.scalar(
                select(Contractor).where(Contractor.phone_number == sender_phone)
            )
            if contractor:
                result = await orchestrator.dispatch_contractor_message(
                    sender_phone, text_body, db
                )
                if result is not None:
                    log.info("Contractor message routed to orchestrator")
                    return

        # ── Tenant flow ────────────────────────────────────────────────────
        tenant = await get_tenant_by_phone(sender_phone, db)

        if not tenant:
            log.warning("Unknown number — not in system")
            await send_text_message(sender_phone, UNKNOWN_NUMBER_MSG)
            return

        conv_state = None
        try:
            conv_state = await get_conversation_state(sender_phone)
        except Exception as exc:
            log.warning("Redis unavailable", error=str(exc))

        if conv_state and conv_state.get("state") == "awaiting_name":
            await handle_onboarding_reply(sender_phone, text_body, db)
            return

        if tenant.name == "Pending":
            log.info("Tenant pending — re-initiating onboarding")
            await initiate_tenant_onboarding(tenant)
            return

        # ── LangGraph maintenance orchestration ─────────────────────────────
        log.info(
            "Tenant identified — dispatching to orchestrator",
            name=tenant.name,
            unit=tenant.unit_number,
            building=tenant.building.name,
        )
        try:
            await orchestrator.dispatch_tenant_message(tenant, message, db)
        except Exception as exc:
            log.exception("Orchestrator failed", error=str(exc))
            try:
                await send_text_message(
                    sender_phone,
                    "Sorry, we hit a technical issue processing your request. "
                    "Please try again in a few minutes.",
                )
            except Exception as send_exc:
                log.warning("Could not send error reply to tenant", error=str(send_exc))
