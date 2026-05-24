"""
Landlord WhatsApp command handler — LLM-powered natural language dispatch.

Claude interprets the landlord's message and calls the appropriate tool.
No rigid syntax required — "add my new tenant 064..." works the same as
"register 381064... 3A".
"""
from __future__ import annotations

import json
import structlog
import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.redis import get_redis
from app.models.building import Building
from app.models.landlord import Landlord
from app.models.tenant import Tenant
from app.services.onboarding_service import initiate_tenant_onboarding
from app.services.rent_service import format_status_for_landlord, get_rent_status, mark_paid
from app.services.whatsapp import send_text_message

_PENDING_DELETE_TTL = 300  # 5 minutes to confirm


async def _get_pending_delete(landlord_phone: str) -> str | None:
    redis = await get_redis()
    return await redis.get(f"pending_delete:{landlord_phone}")


async def _set_pending_delete(landlord_phone: str, tenant_id: str) -> None:
    redis = await get_redis()
    await redis.setex(f"pending_delete:{landlord_phone}", _PENDING_DELETE_TTL, tenant_id)


async def _clear_pending_delete(landlord_phone: str) -> None:
    redis = await get_redis()
    await redis.delete(f"pending_delete:{landlord_phone}")

logger = structlog.get_logger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# ---------------------------------------------------------------------------
# Tool definitions for Claude
# ---------------------------------------------------------------------------

_TOOLS: list[dict] = [
    {
        "name": "register_tenant",
        "description": (
            "Register a new tenant for the landlord's building and send them a "
            "WhatsApp onboarding message asking for their name. "
            "Only call this when BOTH a phone number AND a clear apartment/unit number are present."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": (
                        "Tenant's phone number in E.164 format WITHOUT the leading +. "
                        "Remove ALL spaces, dashes, parentheses, and the leading + sign. "
                        "If the number starts with 0 (local format, e.g. Serbian '064...'), "
                        "drop the leading 0 and prepend country code 381. "
                        "Examples: '+381 60 123 4567' → '381601234567', "
                        "'064 349 2561' → '381643492561'."
                    ),
                },
                "unit": {
                    "type": "string",
                    "description": (
                        "The apartment or unit number INSIDE the building — NOT a street address. "
                        "A street address looks like 'Jurija Gagarina 131' or 'Main St 5' — that is NOT a unit. "
                        "A unit looks like '3A', '12', 'B4', 'stan 7'. "
                        "If the message only contains a street address and no apartment number, "
                        "do NOT call this tool — call ask_clarification instead."
                    ),
                },
            },
            "required": ["phone", "unit"],
        },
    },
    {
        "name": "ask_clarification",
        "description": (
            "Ask the landlord for missing information. "
            "Use when: the apartment/unit number is missing (only a street address was given), "
            "the phone number is missing, or the message is ambiguous."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the landlord. Be short and specific.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "list_tenants",
        "description": (
            "List all tenants registered under this landlord. "
            "Use when the landlord asks who their tenants are, wants to see a list, "
            "asks 'who lives in my building', 'show tenants', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "remove_tenant",
        "description": (
            "Remove / delete a tenant from the building. "
            "Use when landlord says 'remove', 'delete', 'kick out', 'ukloni stanara', etc. "
            "Requires the NUMBER shown next to the tenant in the list (1, 2, 3...). "
            "If the landlord gives a name or phone instead of a number, call ask_clarification "
            "and tell them to type 'tenants' first to see the numbered list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "The list number of the tenant to remove (e.g. '1', '2', '3').",
                },
            },
            "required": ["tenant_id"],
        },
    },
    {
        "name": "resend_onboarding",
        "description": (
            "Resend the onboarding WhatsApp message to a tenant who hasn't received it yet. "
            "Use when the landlord says 'resend', 'send again', 'tenant didn't get message', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "Tenant's phone number — same normalisation rules as register_tenant.",
                },
            },
            "required": ["phone"],
        },
    },
    {
        "name": "add_contractor",
        "description": (
            "Add a new contractor/repairman to the landlord's roster. "
            "Use when landlord says 'add contractor', 'add repairman', 'add electrician/plumber/etc'. "
            "Specialty must be one of: electrical, plumbing, hvac, structural, appliance, general."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contractor's full name."},
                "phone": {"type": "string", "description": "Phone number — same normalisation rules as register_tenant."},
                "specialty": {"type": "string", "description": "One of: electrical, plumbing, hvac, structural, appliance, general."},
                "notes": {"type": "string", "description": "Optional notes about availability or skills."},
            },
            "required": ["name", "phone", "specialty"],
        },
    },
    {
        "name": "mark_rent_paid",
        "description": (
            "Mark a tenant's current month rent as paid. "
            "Use when landlord says 'mark paid', 'tenant paid', 'received rent', etc. "
            "Requires the tenant NUMBER from the list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tenant_number": {
                    "type": "string",
                    "description": "The list number of the tenant (1, 2, 3...). If unclear, ask the landlord to type 'tenants' first.",
                },
                "amount": {
                    "type": "number",
                    "description": "Amount paid in EUR. If not specified, assume full rent amount.",
                },
            },
            "required": ["tenant_number"],
        },
    },
    {
        "name": "rent_overview",
        "description": (
            "Show rent payment status for all tenants. "
            "Use when landlord asks 'who paid rent', 'rent status', 'who owes money', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "reset_workflow",
        "description": (
            "Reset / clear a stuck tenant workflow. "
            "Use when the landlord says 'reset', 'restart', 'tenant is stuck', "
            "'tenant isn't getting replies', 'clear workflow', etc. "
            "Requires the tenant NUMBER from the list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tenant_number": {
                    "type": "string",
                    "description": "The list number of the tenant (1, 2, 3...). Type 'tenants' to see the list.",
                },
            },
            "required": ["tenant_number"],
        },
    },
    {
        "name": "show_help",
        "description": "Show the landlord what they can do. Use when they say 'help', 'what can I do', or the message is unclear.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

_SYSTEM = (
    "You are a property management assistant for a landlord using WhatsApp. "
    "Your only job is to call the right tool based on what the landlord says.\n\n"

    "PHONE NUMBER RULES:\n"
    "- Strip the leading + sign and all spaces, dashes, parentheses.\n"
    "- Serbian local numbers start with 06x (e.g. '064 349 2561'). "
    "Drop the leading 0 and prepend 381 → '381643492561'.\n"
    "- Result must be digits only.\n\n"

    "UNIT vs ADDRESS — THIS IS CRITICAL:\n"
    "- A STREET ADDRESS is 'Street Name + building number', e.g. 'Jurija Gagarina 131', "
    "'Bulevar Oslobođenja 45', 'Main Street 10'. The trailing number is the BUILDING number, NOT the unit.\n"
    "- A UNIT/APARTMENT is a short identifier for a specific flat INSIDE a building: '3A', '12', 'B4', 'stan 7'.\n"
    "- If the landlord gives a street address but NO apartment number, call ask_clarification "
    "and ask which apartment/unit number the tenant lives in.\n\n"

    "Always call exactly one tool. Never reply with plain text."
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def handle_landlord_command(
    landlord: Landlord,
    text: str,
    db: AsyncSession,
) -> bool:
    """
    Ask Claude to interpret the landlord's message and dispatch a tool.
    Returns True if handled (always, for any non-empty message).
    Returns False only if the message is empty.
    """
    if not text.strip():
        return False

    # ── Intercept YES/NO for pending delete confirmation ─────────────────────
    pending_id = await _get_pending_delete(landlord.phone_number)
    if pending_id:
        lower = text.strip().lower()
        if lower in ("yes", "da", "confirm", "delete", "yes delete", "potvrdi"):
            await _exec_confirm_delete(landlord, pending_id, db)
            return True
        elif lower in ("no", "ne", "cancel", "otkazi"):
            await _clear_pending_delete(landlord.phone_number)
            await _reply(landlord.phone_number, "❌ Deletion cancelled.")
            return True
        # Any other message: fall through to Claude (treat as new command)
        await _clear_pending_delete(landlord.phone_number)

    try:
        response = await _client.messages.create(
            model=settings.anthropic_model_fast,
            max_tokens=256,
            system=_SYSTEM,
            tools=_TOOLS,
            messages=[{"role": "user", "content": text}],
        )
    except Exception as exc:
        logger.error("Claude tool dispatch failed", error=str(exc))
        await _reply(landlord.phone_number, "⚠️ AI unavailable. Try: *register <phone> <unit>* or *tenants*")
        return True

    # Find the tool_use block
    tool_call = next((b for b in response.content if b.type == "tool_use"), None)

    if not tool_call:
        # Claude returned text instead of a tool call — unlikely but handle it
        text_block = next((b for b in response.content if b.type == "text"), None)
        reply = text_block.text if text_block else "Type *help* to see available commands."
        await _reply(landlord.phone_number, reply)
        return True

    tool_name = tool_call.name
    tool_input: dict = tool_call.input  # type: ignore[attr-defined]

    logger.info("Landlord tool dispatched", tool=tool_name, input=tool_input)

    if tool_name == "add_contractor":
        await _exec_add_contractor(landlord, tool_input, db)
    elif tool_name == "register_tenant":
        await _exec_register(landlord, tool_input, db)
    elif tool_name == "remove_tenant":
        await _exec_remove_tenant(landlord, tool_input, db)
    elif tool_name == "resend_onboarding":
        await _exec_resend(landlord, tool_input, db)
    elif tool_name == "ask_clarification":
        await _reply(landlord.phone_number, tool_input.get("question", "Could you clarify?"))
    elif tool_name == "mark_rent_paid":
        await _exec_mark_paid(landlord, tool_input, db)
    elif tool_name == "rent_overview":
        await _exec_rent_overview(landlord, db)
    elif tool_name == "list_tenants":
        await _exec_list_tenants(landlord, db)
    elif tool_name == "reset_workflow":
        await _exec_reset_workflow(landlord, tool_input, db)
    elif tool_name == "show_help":
        await _exec_help(landlord)
    else:
        await _reply(landlord.phone_number, f"Unknown tool: {tool_name}")

    return True


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _exec_register(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    phone = str(params.get("phone", "")).strip().lstrip("+").replace(" ", "").replace("-", "")
    unit = str(params.get("unit", "")).strip().upper()

    if not phone or not unit:
        await _reply(landlord.phone_number, "⚠️ I need both a phone number and a unit. Example: *register 381641234567 3A*")
        return

    existing = await db.scalar(select(Tenant).where(Tenant.phone_number == phone))
    if existing:
        await _reply(
            landlord.phone_number,
            f"⚠️ *{phone}* is already registered as *{existing.name}* in unit {existing.unit_number}.",
        )
        return

    building = await db.scalar(
        select(Building).where(Building.landlord_id == landlord.id).limit(1)
    )
    if not building:
        await _reply(landlord.phone_number, "❌ No building found for your account. Contact support.")
        return

    tenant = Tenant(
        building_id=building.id,
        landlord_id=landlord.id,
        name="Pending",
        phone_number=phone,
        unit_number=unit,
        language=landlord.language or "en",
        active=True,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    logger.info("Tenant created via LLM command", phone=phone, unit=unit)

    onboarding_error: str | None = None
    try:
        await initiate_tenant_onboarding(tenant)
    except Exception as exc:
        onboarding_error = str(exc)
        logger.error("Onboarding message failed", phone=phone, error=onboarding_error)

    if onboarding_error:
        await _reply(
            landlord.phone_number,
            f"✅ Tenant record created for unit *{unit}* ({phone}).\n\n"
            f"⚠️ *WhatsApp delivery failed:*\n`{onboarding_error}`\n\n"
            f"Most likely cause: the number *{phone}* has not messaged your bot yet.\n"
            f"Ask them to send any message to *+15556402370* first, then type:\n"
            f"`resend {phone}`",
        )
    else:
        await _reply(
            landlord.phone_number,
            f"✅ Tenant added for unit *{unit}*.\n"
            f"Onboarding message sent to *{phone}* — they'll reply with their name.",
        )


async def _exec_add_contractor(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    from app.models.contractor import Contractor
    phone = str(params.get("phone", "")).strip().lstrip("+").replace(" ", "").replace("-", "")
    name = str(params.get("name", "")).strip()
    specialty = str(params.get("specialty", "general")).strip().lower()
    notes = str(params.get("notes", "")).strip() or None

    valid = {"electrical", "plumbing", "hvac", "structural", "appliance", "general"}
    if specialty not in valid:
        specialty = "general"

    existing = await db.scalar(select(Contractor).where(Contractor.phone_number == phone))
    if existing:
        await _reply(landlord.phone_number, f"⚠️ *{phone}* is already registered as contractor *{existing.name}*.")
        return

    contractor = Contractor(
        landlord_id=landlord.id,
        name=name,
        phone_number=phone,
        specialties=[specialty],
        notes=notes,
        active=True,
    )
    db.add(contractor)
    await db.commit()
    logger.info("Contractor added via WhatsApp", name=name, phone=phone, specialty=specialty)
    await _reply(
        landlord.phone_number,
        f"✅ *{name}* added as *{specialty}* contractor ({phone}).\n"
        f"They'll be contacted automatically when a matching issue is approved.",
    )


async def _exec_remove_tenant(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    import uuid as _uuid
    number = str(params.get("tenant_id", "")).strip()

    # Look up UUID from the cached list mapping
    redis = await get_redis()
    raw = await redis.get(f"tenant_list:{landlord.phone_number}")
    if not raw:
        await _reply(
            landlord.phone_number,
            "⚠️ Please type *tenants* first to see the numbered list, then *remove <number>*.",
        )
        return

    mapping: dict = json.loads(raw)
    tenant_uuid = mapping.get(number)
    if not tenant_uuid:
        await _reply(
            landlord.phone_number,
            f"⚠️ No tenant number *{number}* in the list.\nType *tenants* to refresh the list.",
        )
        return

    tenant = await db.scalar(select(Tenant).where(Tenant.id == _uuid.UUID(tenant_uuid)))
    if not tenant:
        await _reply(landlord.phone_number, "⚠️ Tenant not found.")
        return
    # Store pending delete in Redis
    await _set_pending_delete(landlord.phone_number, str(tenant.id))
    await _reply(
        landlord.phone_number,
        f"⚠️ Are you sure you want to remove:\n\n"
        f"*{tenant.name}* — unit *{tenant.unit_number}* ({tenant.phone_number})\n\n"
        f"Reply *YES* to confirm or *NO* to cancel.\n"
        f"_(This will expire in 5 minutes)_",
    )


async def _exec_confirm_delete(landlord: Landlord, tenant_id: str, db: AsyncSession) -> None:
    import uuid as _uuid
    tenant = await db.scalar(select(Tenant).where(Tenant.id == _uuid.UUID(tenant_id)))
    if not tenant:
        await _clear_pending_delete(landlord.phone_number)
        await _reply(landlord.phone_number, "⚠️ Tenant no longer exists.")
        return

    name, unit, phone = tenant.name, tenant.unit_number, tenant.phone_number
    await db.delete(tenant)
    await db.commit()
    await _clear_pending_delete(landlord.phone_number)
    logger.info("Tenant removed by landlord", name=name, unit=unit, phone=phone)
    await _reply(
        landlord.phone_number,
        f"✅ *{name}* (unit {unit}) has been removed from your building.",
    )


async def _exec_resend(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    phone = str(params.get("phone", "")).strip().lstrip("+").replace(" ", "").replace("-", "")
    tenant = await db.scalar(select(Tenant).where(Tenant.phone_number == phone))
    if not tenant:
        await _reply(landlord.phone_number, f"⚠️ No tenant found with number *{phone}*.")
        return
    if tenant.name != "Pending":
        await _reply(landlord.phone_number, f"ℹ️ *{tenant.name}* (unit {tenant.unit_number}) is already fully registered.")
        return
    try:
        await initiate_tenant_onboarding(tenant)
        await _reply(landlord.phone_number, f"✅ Onboarding message re-sent to *{phone}*.")
    except Exception as exc:
        await _reply(
            landlord.phone_number,
            f"⚠️ Still failing: `{exc}`\n\n"
            f"The number *{phone}* must send any message to *+15556402370* first to opt in.",
        )


async def _exec_list_tenants(landlord: Landlord, db: AsyncSession) -> None:
    result = await db.execute(
        select(Tenant)
        .where(Tenant.landlord_id == landlord.id)
        .options(selectinload(Tenant.building))
        .order_by(Tenant.unit_number)
    )
    tenants = result.scalars().all()

    if not tenants:
        await _reply(landlord.phone_number, "No tenants yet.\nSay *register <phone> <unit>* to add one.")
        return

    # Store number→UUID mapping in Redis so remove can use simple numbers
    redis = await get_redis()
    mapping = {str(i): str(t.id) for i, t in enumerate(tenants, 1)}
    await redis.setex(f"tenant_list:{landlord.phone_number}", 600, json.dumps(mapping))

    lines = ["📋 *Your tenants:*\n"]
    for i, t in enumerate(tenants, 1):
        icon = "✅" if t.name != "Pending" else "⏳"
        lines.append(f"*{i}.* {icon} Unit *{t.unit_number}* — {t.name} ({t.phone_number})")
    lines.append("\n_To remove: type_ *remove 2*")

    await _reply(landlord.phone_number, "\n".join(lines))


async def _exec_mark_paid(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    from decimal import Decimal
    import uuid as _uuid

    number = str(params.get("tenant_number", "")).strip()
    redis = await get_redis()
    raw = await redis.get(f"tenant_list:{landlord.phone_number}")
    if not raw:
        await _reply(landlord.phone_number, "⚠️ Type *tenants* first to see the list, then *mark paid <number>*.")
        return

    mapping: dict = json.loads(raw)
    tenant_uuid = mapping.get(number)
    if not tenant_uuid:
        await _reply(landlord.phone_number, f"⚠️ No tenant #{number}. Type *tenants* to refresh.")
        return

    tenant = await db.scalar(select(Tenant).where(Tenant.id == _uuid.UUID(tenant_uuid)))
    if not tenant:
        await _reply(landlord.phone_number, "⚠️ Tenant not found.")
        return

    raw_amount = params.get("amount")
    amount = Decimal(str(raw_amount)) if raw_amount else None
    record = await mark_paid(db, tenant, amount=amount)

    paid_str = f"€{record.amount_paid:,.2f}"
    await _reply(
        landlord.phone_number,
        f"✅ Marked *{tenant.name}* (unit {tenant.unit_number}) as paid {paid_str} for this month.",
    )


async def _exec_rent_overview(landlord: Landlord, db: AsyncSession) -> None:
    result = await db.execute(
        select(Tenant)
        .where(Tenant.landlord_id == landlord.id, Tenant.name != "Pending")
        .order_by(Tenant.unit_number)
    )
    tenants = result.scalars().all()

    if not tenants:
        await _reply(landlord.phone_number, "No active tenants yet.")
        return

    lines = ["💰 *Rent overview — this month:*\n"]
    for t in tenants:
        status = await get_rent_status(db, t)
        lines.append(format_status_for_landlord(t.name, t.unit_number, status))

    await _reply(landlord.phone_number, "\n".join(lines))


async def _exec_reset_workflow(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    """Clear a tenant's stuck LangGraph checkpoint so they can start fresh."""
    import uuid as _uuid

    number = str(params.get("tenant_number", "")).strip()
    redis = await get_redis()
    raw = await redis.get(f"tenant_list:{landlord.phone_number}")
    if not raw:
        await _reply(
            landlord.phone_number,
            "⚠️ Type *tenants* first to see the numbered list, then *reset <number>*.",
        )
        return

    mapping: dict = json.loads(raw)
    tenant_uuid = mapping.get(number)
    if not tenant_uuid:
        await _reply(
            landlord.phone_number,
            f"⚠️ No tenant #{number}. Type *tenants* to refresh the list.",
        )
        return

    tenant = await db.scalar(select(Tenant).where(Tenant.id == _uuid.UUID(tenant_uuid)))
    if not tenant:
        await _reply(landlord.phone_number, "⚠️ Tenant not found.")
        return

    deleted = await redis.delete(
        f"lg:ckpt:{tenant.phone_number}",
        f"lg:writes:{tenant.phone_number}",
    )
    logger.info("Workflow reset by landlord", tenant=tenant.name, phone=tenant.phone_number, keys_deleted=deleted)

    await _reply(
        landlord.phone_number,
        f"🔄 Workflow reset for *{tenant.name}* (unit {tenant.unit_number}).\n"
        f"They can now send a fresh message and the conversation will restart from the beginning.",
    )


async def _exec_help(landlord: Landlord) -> None:
    await _reply(
        landlord.phone_number,
        "👋 *PropFlow — what you can say:*\n\n"
        "➕ *Add tenant:* _register 381641234567 apartment 3A_\n"
        "📋 *List tenants:* _who are my tenants_\n"
        "🗑️ *Remove tenant:* _remove 2_ (use number from list)\n"
        "🔄 *Reset stuck tenant:* _reset 1_ (clears stuck workflow)\n\n"
        "💰 *Rent:*\n"
        "  _who paid rent_ — full overview\n"
        "  _mark paid 1_ — mark tenant #1 as paid\n"
        "  _mark paid 2 amount 800_ — partial payment\n\n"
        "You can write naturally — I'll understand! 🤖",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _reply(phone: str, text: str) -> None:
    try:
        await send_text_message(phone, text)
    except Exception as exc:
        logger.error("WhatsApp reply failed", phone=phone, error=str(exc))
