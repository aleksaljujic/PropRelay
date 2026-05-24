"""
Hybrid tenant onboarding service.

Flow:
  1. Landlord seeds tenant with name="Pending" + phone + unit
  2. initiate_tenant_onboarding() sends a WhatsApp welcome → sets Redis state
  3. Tenant replies with their name
  4. handle_onboarding_reply() saves name, clears state, sends confirmation

Redis key: conv:<phone>  →  {"state": "awaiting_name", "tenant_id": "<uuid>"}
"""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.redis import (
    clear_conversation_state,
    get_conversation_state,
    set_conversation_state,
)
from app.models.tenant import Tenant
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Message templates (English)
# ---------------------------------------------------------------------------

UNKNOWN_NUMBER_MSG = (
    "Your number is not registered in our system.\n"
    "Please contact your landlord to get access."
)


def _welcome_msg(building_name: str) -> str:
    return (
        f"👋 Hello! Your landlord has added you to PropFlow for *{building_name}*.\n\n"
        "Through this number you can submit maintenance requests and receive updates.\n\n"
        "What is your full name? (Please reply with your first and last name)\n\n"
        "⚠️ Note: This service is powered by PropFlow AI."
    )


def _confirmation_msg(name: str, building_name: str, unit_number: str) -> str:
    return (
        f"✅ Welcome, {name}! You are now registered at *{building_name}*, apartment *{unit_number}*.\n\n"
        "You can report maintenance issues at any time — just describe the problem "
        "or send a photo. We'll take care of it! 🔧"
    )


def _ask_name_again_msg() -> str:
    return (
        "Please reply with your full name (first and last name).\n"
        "Example: *Maria Schmidt*"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def initiate_tenant_onboarding(tenant: Tenant) -> None:
    """
    Called right after landlord adds a tenant (name="Pending").
    Sends a WhatsApp welcome message and sets Redis state to awaiting_name.
    """
    from app.database import async_session_factory  # late import to avoid circles

    # Reload with building relationship (tenant passed in may not have it loaded)
    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant)
            .where(Tenant.id == tenant.id)
            .options(selectinload(Tenant.building))
        )
        fresh = result.scalar_one_or_none()

    if not fresh or not fresh.building:
        logger.error(
            "Cannot onboard: building not found",
            tenant_id=str(tenant.id),
            phone=tenant.phone_number,
        )
        return

    building_name = fresh.building.name

    # Persist conversation state in Redis (24 h TTL)
    try:
        await set_conversation_state(
            tenant.phone_number,
            {"state": "awaiting_name", "tenant_id": str(tenant.id)},
        )
    except Exception as exc:
        logger.warning("Redis unavailable — onboarding state lost on restart", error=str(exc))

    # Send welcome WhatsApp message
    try:
        await send_text_message(tenant.phone_number, _welcome_msg(building_name))
        logger.info(
            "Onboarding initiated",
            phone=tenant.phone_number,
            unit=tenant.unit_number,
            building=building_name,
        )
    except Exception as exc:
        logger.error(
            "Failed to send onboarding message",
            phone=tenant.phone_number,
            error=str(exc),
        )


async def handle_onboarding_reply(
    phone_number: str,
    message_text: str,
    db: AsyncSession,
) -> None:
    """
    Called when a message arrives from a phone currently in awaiting_name state.
    Saves the name, marks tenant active, sends confirmation, clears Redis state.
    """
    name = message_text.strip()

    # Basic validation — require at least two words
    if len(name.split()) < 2:
        await send_text_message(phone_number, _ask_name_again_msg())
        return

    # Load tenant + building
    result = await db.execute(
        select(Tenant)
        .where(Tenant.phone_number == phone_number)
        .options(selectinload(Tenant.building))
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        logger.error("Tenant vanished during onboarding", phone=phone_number)
        return

    # Persist name
    tenant.name = name
    tenant.active = True
    await db.commit()
    await db.refresh(tenant)

    # Clear Redis state
    try:
        await clear_conversation_state(phone_number)
    except Exception:
        pass

    # Send confirmation
    building_name = tenant.building.name if tenant.building else "your building"
    try:
        await send_text_message(
            phone_number,
            _confirmation_msg(name, building_name, tenant.unit_number),
        )
    except Exception as exc:
        logger.error("Failed to send confirmation", phone=phone_number, error=str(exc))

    logger.info(
        "Tenant onboarding complete",
        phone=phone_number,
        name=name,
        unit=tenant.unit_number,
    )
