"""
Tenant self-registration flow.

Conversation steps:
  1. Unknown phone messages bot → welcome, ask for full name
  2. User replies with name     → ask for unit number
  3. User replies with unit     → create Tenant in DB, confirm

State is held in memory (fine for demo; swap for Redis in production).
"""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.building import Building
from app.models.tenant import Tenant

logger = structlog.get_logger(__name__)

# phone → {"step": "awaiting_name"|"awaiting_unit", "name": str, "building_whatsapp": str}
_pending: dict[str, dict] = {}


def is_registering(phone: str) -> bool:
    """Return True if this phone is mid-registration."""
    return phone in _pending


async def start_registration(phone: str, building_whatsapp: str) -> str:
    """
    Kick off the registration flow for an unknown number.
    Returns the first message to send back.
    """
    _pending[phone] = {
        "step": "awaiting_name",
        "building_whatsapp": building_whatsapp,
    }
    logger.info("Registration started", phone=phone)
    return (
        "👋 Welcome to PropFlow!\n\n"
        "Your number is not registered yet. Let's get you set up.\n\n"
        "Please reply with your *full name* (first and last name)."
    )


async def handle_registration_step(phone: str, text: str, db: AsyncSession) -> str:
    """
    Advance the registration state machine by one step.
    Returns the next bot message to send.
    """
    state = _pending.get(phone)
    if not state:
        return "Something went wrong. Please send any message to start over."

    step = state["step"]
    text = text.strip()

    # ── Step 1: collect full name ────────────────────────────────────────────
    if step == "awaiting_name":
        if len(text.split()) < 2:
            return (
                "Please enter your *full name* — first and last name.\n"
                "Example: *John Smith*"
            )
        state["name"] = text
        state["step"] = "awaiting_unit"
        _pending[phone] = state
        return (
            f"Nice to meet you, *{text}*! 🏠\n\n"
            "What is your *unit number*?\n"
            "Example: *4B*, *12*, *2A*"
        )

    # ── Step 2: collect unit number, create tenant ───────────────────────────
    elif step == "awaiting_unit":
        unit = text.upper()
        if not unit:
            return "Please enter your unit number (e.g. *4B*, *12*, *2A*)."

        building_whatsapp = state["building_whatsapp"]
        name = state["name"]

        # Look up building by the bot's WhatsApp number
        result = await db.execute(
            select(Building).where(Building.whatsapp_number == building_whatsapp)
        )
        building = result.scalar_one_or_none()

        if not building:
            logger.error("Building not found during registration", wa=building_whatsapp)
            _pending.pop(phone, None)
            return (
                "❌ Sorry, we couldn't find your building in our system.\n"
                "Please contact your landlord directly."
            )

        # Create the tenant
        tenant = Tenant(
            building_id=building.id,
            landlord_id=building.landlord_id,
            name=name,
            phone_number=phone,
            unit_number=unit,
            language="en",
            active=True,
        )
        db.add(tenant)
        await db.commit()

        _pending.pop(phone, None)
        logger.info("Tenant registered via WhatsApp", phone=phone, name=name, unit=unit)

        return (
            f"✅ You're registered!\n\n"
            f"*{name}* — Unit {unit}, {building.name}\n\n"
            "You can now report maintenance issues or send us any questions. "
            "How can we help you today?"
        )

    else:
        _pending.pop(phone, None)
        return "Something went wrong. Please send any message to start over."
