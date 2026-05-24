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
from app.services.onboarding_service import (
    UNKNOWN_NUMBER_MSG,
    handle_onboarding_reply,
    initiate_tenant_onboarding,
)
from app.services.tenant_lookup import get_tenant_by_phone
from app.services.whatsapp import send_text_message

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

    # Extract text body (empty string for non-text messages)
    text_body = ""
    if msg_type == "text":
        text_body = message.get("text", {}).get("body", "")
    elif msg_type == "image":
        logger.info("Image received", media_id=message.get("image", {}).get("id", ""))
    elif msg_type == "audio":
        logger.info("Audio received", media_id=message.get("audio", {}).get("id", ""))
    elif msg_type == "video":
        logger.info("Video received", media_id=message.get("video", {}).get("id", ""))
    elif msg_type == "document":
        logger.info("Document received", media_id=message.get("document", {}).get("id", ""))

    log = logger.bind(phone=sender_phone, message_id=message_id, type=msg_type)
    log.info("Message received", text=text_body or f"[{msg_type}]")

    async with async_session_factory() as db:
        # ── Step 1: identify sender ──────────────────────────────────────────
        tenant = await get_tenant_by_phone(sender_phone, db)

        if not tenant:
            log.warning("Unknown number — not in system")
            await send_text_message(sender_phone, UNKNOWN_NUMBER_MSG)
            return

        # ── Step 2: check Redis conversation state ───────────────────────────
        conv_state = None
        try:
            conv_state = await get_conversation_state(sender_phone)
        except Exception as exc:
            log.warning("Redis unavailable", error=str(exc))

        # ── Step 3: route by state ───────────────────────────────────────────
        if conv_state and conv_state.get("state") == "awaiting_name":
            await handle_onboarding_reply(sender_phone, text_body, db)
            return

        if tenant.name == "Pending":
            # Re-trigger onboarding if state was lost (e.g. Redis restart)
            log.info("Tenant pending — re-initiating onboarding")
            await initiate_tenant_onboarding(tenant)
            return

        # ── Step 4: fully registered tenant ─────────────────────────────────
        log.info(
            "Tenant identified",
            name=tenant.name,
            unit=tenant.unit_number,
            building=tenant.building.name,
        )
        await send_text_message(
            sender_phone,
            f"Got it, {tenant.name}! Your message has been received. We'll get back to you shortly.",
        )
        # TODO: await agent_router.dispatch(tenant, message)
