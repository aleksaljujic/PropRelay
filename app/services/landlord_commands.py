"""
Landlord WhatsApp command handler — LLM-powered natural language dispatch.

Claude interprets the landlord's message and calls the appropriate tool.
No rigid syntax required — "add my new tenant 064..." works the same as
"register 381064... 3A".
"""
from __future__ import annotations

import json
import re
import structlog
import anthropic
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from datetime import datetime, timezone

from app.config import settings
from app.core.redis import get_redis
from app.models.building import Building
from app.models.contractor import Contractor
from app.models.landlord import Landlord
from app.models.tenant import Tenant
from app.models.rent_payment import RentPayment
from app.models.ticket import ConversationState, Ticket, TicketStatus
from app.services.onboarding_service import initiate_tenant_onboarding
from app.services.rent_service import format_status_for_landlord, get_rent_status, mark_paid
from app.services.ticket_service import set_ticket_status
from app.services.whatsapp import send_text_message

_PENDING_DELETE_TTL = 300    # 5 min to confirm delete
_PENDING_REGISTER_TTL = 300  # 5 min to complete registration


async def _get_pending_delete(landlord_phone: str) -> str | None:
    redis = await get_redis()
    return await redis.get(f"pending_delete:{landlord_phone}")


async def _set_pending_delete(landlord_phone: str, tenant_id: str) -> None:
    redis = await get_redis()
    await redis.setex(f"pending_delete:{landlord_phone}", _PENDING_DELETE_TTL, tenant_id)


async def _clear_pending_delete(landlord_phone: str) -> None:
    redis = await get_redis()
    await redis.delete(f"pending_delete:{landlord_phone}")


async def _get_pending_registration(landlord_phone: str) -> dict | None:
    redis = await get_redis()
    raw = await redis.get(f"pending_register:{landlord_phone}")
    return json.loads(raw) if raw else None


async def _set_pending_registration(landlord_phone: str, data: dict) -> None:
    redis = await get_redis()
    await redis.setex(f"pending_register:{landlord_phone}", _PENDING_REGISTER_TTL, json.dumps(data))


async def _clear_pending_registration(landlord_phone: str) -> None:
    redis = await get_redis()
    await redis.delete(f"pending_register:{landlord_phone}")


def _normalize_phone(raw: str) -> str:
    """Normalise any phone format to E.164 digits without leading +."""
    phone = raw.strip().lstrip("+").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("0") and len(phone) <= 10:  # Serbian local 06x / 07x
        phone = "381" + phone[1:]
    return phone

logger = structlog.get_logger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# ---------------------------------------------------------------------------
# Tool definitions for Claude
# ---------------------------------------------------------------------------

_TOOLS: list[dict] = [
    {
        "name": "start_registration",
        "description": (
            "Start the guided step-by-step tenant registration flow. "
            "Use when the landlord wants to add, register, or onboard a new tenant — "
            "regardless of how they phrase it. "
            "No parameters needed — the bot will ask for phone number and apartment number one at a time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
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
        "name": "list_contractors",
        "description": (
            "List all contractors/workers in the landlord's roster. "
            "Use when landlord says 'workers', 'contractors', 'repairmen', "
            "'show workers', 'who can fix things', 'list contractors', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_tickets",
        "description": (
            "List recent maintenance tickets across the landlord's portfolio. "
            "Use when landlord says 'tickets', 'jobs', 'open issues', 'show maintenance', "
            "'what needs fixing', 'pending work', etc. "
            "Returns OPEN tickets by default — set status='all' to include closed ones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Optional filter: 'open' (default), 'all', or a specific status like 'completed', 'dispatched'.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "mark_ticket_done",
        "description": (
            "Mark a maintenance ticket as completed/resolved. "
            "Use when landlord says 'done', 'fixed', 'completed', 'close ticket', 'resolved', etc. "
            "Requires the ticket NUMBER from the list shown by list_tickets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_number": {
                    "type": "string",
                    "description": "The list number of the ticket (1, 2, 3...). Type 'tickets' first to see the list.",
                },
            },
            "required": ["ticket_number"],
        },
    },
    {
        "name": "message_tenant",
        "description": (
            "Send a direct WhatsApp message to a specific tenant. "
            "Use when landlord says 'message <name>', 'tell <name> ...', 'text tenant <name>', etc. "
            "Requires either a tenant NUMBER from the list, or a name that can be matched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tenant_number": {
                    "type": "string",
                    "description": "List number of the tenant (1, 2, 3...). Use 'tenants' to see the list.",
                },
                "name_hint": {
                    "type": "string",
                    "description": "Tenant name (partial match) if no number was given. Optional.",
                },
                "text": {
                    "type": "string",
                    "description": "The message body to send to the tenant.",
                },
            },
            "required": ["text"],
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

async def handle_pending_delete_reply(
    landlord: Landlord,
    text: str,
    db: AsyncSession,
) -> bool:
    """Handle YES/NO while a tenant removal is awaiting confirmation."""
    pending_id = await _get_pending_delete(landlord.phone_number)
    if not pending_id:
        return False

    lower = text.strip().lower()
    if lower in ("yes", "da", "confirm", "delete", "yes delete", "potvrdi"):
        await _exec_confirm_delete(landlord, pending_id, db)
        return True
    if lower in ("no", "ne", "cancel", "otkazi"):
        await _clear_pending_delete(landlord.phone_number)
        await _reply(landlord.phone_number, "❌ Deletion cancelled.")
        return True
    return False


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

    lower = text.strip().lower()

    # ── Direct commands (no Claude API — instant & reliable) ─────────────────
    if lower in ("tenants", "tenant", "stanari", "stanar"):
        await _exec_list_tenants(landlord, db)
        return True
    if lower in ("help", "commands", "pomoc", "?"):
        await _exec_help(landlord)
        return True
    if lower in ("contractors", "contractor", "workers", "worker", "radnici"):
        await _exec_list_contractors(landlord, db)
        return True
    if lower in ("tickets", "ticket", "requests", "tiketi"):
        await _exec_list_tickets(landlord, {}, db)
        return True
    if lower in ("rent", "rents", "rent overview", "kira"):
        await _exec_rent_overview(landlord, db)
        return True

    remove_match = re.match(r"^(?:remove|delete|ukloni)\s+(\d+)$", lower)
    if remove_match:
        await _exec_remove_tenant(landlord, {"tenant_id": remove_match.group(1)}, db)
        return True

    # ── Intercept cancel for any pending multi-step flow ─────────────────────
    if lower in ("cancel", "otkazi", "stop", "quit"):
        await _clear_pending_registration(landlord.phone_number)
        await _clear_pending_delete(landlord.phone_number)
        await _reply(landlord.phone_number, "❌ Cancelled.")
        return True

    # ── Intercept replies for pending step-by-step registration ──────────────
    pending_reg = await _get_pending_registration(landlord.phone_number)
    if pending_reg:
        step = pending_reg.get("step")
        if step == "awaiting_phone":
            phone = _normalize_phone(text)
            if not phone.isdigit() or len(phone) < 7:
                await _reply(
                    landlord.phone_number,
                    "⚠️ That doesn't look like a valid phone number.\n"
                    "Please send just the number, e.g. *064 349 2561* or *+381 64 349 2561*\n\n"
                    "Type *cancel* to stop.",
                )
                return True
            await _set_pending_registration(landlord.phone_number, {"step": "awaiting_unit", "phone": phone})
            await _reply(
                landlord.phone_number,
                f"📱 Got it: *{phone}*\n\n"
                f"🏠 What's their apartment / unit number?\n"
                f"(e.g. *3A*, *12*, *B4* — NOT the building address)\n\n"
                f"Type *cancel* to stop.",
            )
            return True
        elif step == "awaiting_unit":
            unit = text.strip().upper()
            phone = pending_reg.get("phone", "")
            await _clear_pending_registration(landlord.phone_number)
            await _exec_register(landlord, {"phone": phone, "unit": unit}, db)
            return True

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

    if tool_name == "start_registration":
        await _exec_start_registration(landlord)
    elif tool_name == "add_contractor":
        await _exec_add_contractor(landlord, tool_input, db)
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
    elif tool_name == "list_contractors":
        await _exec_list_contractors(landlord, db)
    elif tool_name == "list_tickets":
        await _exec_list_tickets(landlord, tool_input, db)
    elif tool_name == "mark_ticket_done":
        await _exec_mark_ticket_done(landlord, tool_input, db)
    elif tool_name == "message_tenant":
        await _exec_message_tenant(landlord, tool_input, db)
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

async def _exec_start_registration(landlord: Landlord) -> None:
    """Kick off the guided step-by-step registration flow."""
    await _set_pending_registration(landlord.phone_number, {"step": "awaiting_phone"})
    await _reply(
        landlord.phone_number,
        "➕ *Add new tenant*\n\n"
        "📱 What's the tenant's phone number?\n"
        "(e.g. *064 349 2561* or *+381 64 349 2561*)\n\n"
        "Type *cancel* to stop.",
    )


async def _exec_register(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    phone = _normalize_phone(str(params.get("phone", "")))
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

    if tenant.landlord_id != landlord.id:
        await _clear_pending_delete(landlord.phone_number)
        await _reply(landlord.phone_number, "⚠️ That tenant is not on your account.")
        return

    name, unit, phone = tenant.name, tenant.unit_number, tenant.phone_number

    try:
        # Clear workflow + list cache in Redis
        redis = await get_redis()
        from app.storage.redis_checkpoint import RedisCheckpointSaver

        await RedisCheckpointSaver().adelete_thread(phone)
        for pattern in (f"lg:ckpt:{phone}", f"lg:writes:{phone}", f"tenant_list:{landlord.phone_number}"):
            await redis.delete(pattern)

        # Remove dependent rows — tickets block hard delete (tenant_id NOT NULL)
        await db.execute(
            delete(ConversationState).where(ConversationState.phone_number == phone)
        )
        await db.execute(delete(Ticket).where(Ticket.tenant_id == tenant.id))
        await db.execute(delete(RentPayment).where(RentPayment.tenant_id == tenant.id))

        await db.delete(tenant)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Tenant delete failed", tenant_id=tenant_id, error=str(exc))
        await _reply(
            landlord.phone_number,
            "⚠️ Could not remove tenant — please try again or contact support.",
        )
        return

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
        .where(Tenant.landlord_id == landlord.id, Tenant.active.is_(True))
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
        "👋 *PropRelay — what you can say:*\n\n"
        "👤 *Tenants*\n"
        "  • _register_ or _add new tenant_ — guided onboarding\n"
        "  • _tenants_ — numbered list of your tenants\n"
        "  • _remove 2_ — delete tenant #2\n"
        "  • _reset 1_ — clear a stuck conversation\n"
        "  • _message 1 Hello, I'm raising rent by €50_ — DM tenant #1\n\n"
        "👷 *Workers / contractors*\n"
        "  • _workers_ — full roster with specialties\n"
        "  • _add electrician John, phone +49170...._\n\n"
        "🛠 *Maintenance tickets*\n"
        "  • _tickets_ — open jobs across all buildings\n"
        "  • _tickets all_ — include resolved ones\n"
        "  • _done 1_ — mark ticket #1 as fixed\n"
        "  • Approval ping arrives automatically — reply *YES / NO* or send a custom message\n\n"
        "💰 *Rent*\n"
        "  • _rent_ — payment status overview\n"
        "  • _mark paid 1_ — record full rent for tenant #1\n"
        "  • _mark paid 2 amount 800_ — partial payment\n\n"
        "_Type *cancel* anytime to stop. Write naturally — AI understands._",
    )


async def _exec_list_contractors(landlord: Landlord, db: AsyncSession) -> None:
    result = await db.execute(
        select(Contractor)
        .where(Contractor.landlord_id == landlord.id)
        .order_by(Contractor.name)
    )
    contractors = list(result.scalars().all())

    if not contractors:
        await _reply(
            landlord.phone_number,
            "👷 No contractors yet.\n\nAdd one: _add plumber John, phone +49170123456_",
        )
        return

    redis = await get_redis()
    mapping = {str(i): str(c.id) for i, c in enumerate(contractors, 1)}
    await redis.setex(f"contractor_list:{landlord.phone_number}", 600, json.dumps(mapping))

    lines = ["👷 *Your workers:*\n"]
    for i, c in enumerate(contractors, 1):
        status = "✅" if c.active else "🚫"
        specs = ", ".join(c.specialties or []) or "—"
        lang = (c.language or "en").upper()
        lines.append(
            f"*{i}.* {status} {c.name} ({lang})\n"
            f"    📞 {c.phone_number}\n"
            f"    🔧 {specs}"
        )
    lines.append("\n_AI auto-dispatches based on specialty when you approve a ticket._")

    await _reply(landlord.phone_number, "\n".join(lines))


async def _exec_list_tickets(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    status_filter = str(params.get("status") or "open").strip().lower()

    q = (
        select(Ticket)
        .join(Tenant, Ticket.tenant_id == Tenant.id)
        .where(Tenant.landlord_id == landlord.id)
        .order_by(Ticket.created_at.desc())
        .limit(20)
    )
    if status_filter == "open":
        # Open = anything not closed
        closed = {TicketStatus.completed, TicketStatus.rejected, TicketStatus.self_resolved}
        result = await db.execute(q)
        tickets = [t for t in result.scalars().all() if t.status not in closed]
    elif status_filter == "all":
        result = await db.execute(q)
        tickets = list(result.scalars().all())
    else:
        # Specific status name
        try:
            target = TicketStatus(status_filter)
            result = await db.execute(q.where(Ticket.status == target))
            tickets = list(result.scalars().all())
        except ValueError:
            result = await db.execute(q)
            tickets = list(result.scalars().all())

    if not tickets:
        await _reply(landlord.phone_number, f"🛠 No {status_filter} tickets right now.")
        return

    # Load tenants in a single query for names + units
    tenant_ids = list({t.tenant_id for t in tickets})
    t_result = await db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids)))
    tenants_by_id = {tt.id: tt for tt in t_result.scalars().all()}

    redis = await get_redis()
    mapping = {str(i): str(t.id) for i, t in enumerate(tickets, 1)}
    await redis.setex(f"ticket_list:{landlord.phone_number}", 600, json.dumps(mapping))

    status_emoji = {
        TicketStatus.new: "🆕",
        TicketStatus.triaged: "🔎",
        TicketStatus.awaiting_landlord: "⏳",
        TicketStatus.approved: "✅",
        TicketStatus.dispatched: "📨",
        TicketStatus.scheduled: "📅",
        TicketStatus.completed: "🏁",
        TicketStatus.rejected: "❌",
        TicketStatus.self_resolved: "💡",
    }
    urgency_emoji = {"emergency": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢"}

    title = "open tickets" if status_filter == "open" else f"tickets ({status_filter})"
    lines = [f"🛠 *Recent {title}:*\n"]
    for i, t in enumerate(tickets, 1):
        tenant = tenants_by_id.get(t.tenant_id)
        tenant_label = (
            f"{tenant.name} (unit {tenant.unit_number})"
            if tenant else "Unknown tenant"
        )
        emoji = status_emoji.get(t.status, "•")
        u_emoji = urgency_emoji.get(t.urgency.value if hasattr(t.urgency, "value") else str(t.urgency), "")
        cat = t.category.value if hasattr(t.category, "value") else str(t.category)
        desc = (t.ai_diagnosis or t.description or "").strip()
        if len(desc) > 70:
            desc = desc[:67] + "..."
        lines.append(
            f"*{i}.* {emoji} *{(t.status.value if hasattr(t.status, 'value') else t.status).upper()}*"
            f"  {u_emoji}{cat}\n"
            f"    {tenant_label}\n"
            f"    _{desc}_"
        )
    lines.append("\n_To close: *done 1*_")

    await _reply(landlord.phone_number, "\n".join(lines))


async def _exec_mark_ticket_done(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    import uuid as _uuid

    number = str(params.get("ticket_number", "")).strip()
    redis = await get_redis()
    raw = await redis.get(f"ticket_list:{landlord.phone_number}")
    if not raw:
        await _reply(
            landlord.phone_number,
            "⚠️ Type *tickets* first to see the numbered list, then *done <number>*.",
        )
        return

    mapping: dict = json.loads(raw)
    ticket_uuid = mapping.get(number)
    if not ticket_uuid:
        await _reply(landlord.phone_number, f"⚠️ No ticket #{number}. Type *tickets* to refresh.")
        return

    ticket = await db.scalar(select(Ticket).where(Ticket.id == _uuid.UUID(ticket_uuid)))
    if not ticket:
        await _reply(landlord.phone_number, "⚠️ Ticket not found.")
        return

    await set_ticket_status(
        db, ticket,
        TicketStatus.completed,
        resolved_at=datetime.now(timezone.utc),
    )

    # Notify the tenant their issue is closed
    tenant = await db.scalar(select(Tenant).where(Tenant.id == ticket.tenant_id))
    if tenant:
        try:
            await send_text_message(
                tenant.phone_number,
                f"🏁 Your maintenance ticket has been marked as *resolved* by your landlord. "
                f"If the issue isn't actually fixed, just reply to this chat and I'll reopen it.",
            )
        except Exception as exc:
            logger.warning("Could not notify tenant of closure", error=str(exc))

    logger.info("Ticket marked done by landlord", ticket_id=ticket_uuid, landlord=landlord.phone_number)
    await _reply(
        landlord.phone_number,
        f"✅ Ticket #{number} marked as *DONE*. Tenant has been notified.",
    )


async def _exec_message_tenant(landlord: Landlord, params: dict, db: AsyncSession) -> None:
    import uuid as _uuid

    text = str(params.get("text") or "").strip()
    if not text:
        await _reply(landlord.phone_number, "⚠️ I need the message text. Example: _message 1 Hello_")
        return

    number = str(params.get("tenant_number") or "").strip()
    name_hint = str(params.get("name_hint") or "").strip().lower()
    tenant: Tenant | None = None

    # 1) Resolve by list number first
    if number:
        redis = await get_redis()
        raw = await redis.get(f"tenant_list:{landlord.phone_number}")
        if raw:
            mapping = json.loads(raw)
            tenant_uuid = mapping.get(number)
            if tenant_uuid:
                tenant = await db.scalar(select(Tenant).where(Tenant.id == _uuid.UUID(tenant_uuid)))

    # 2) Else try name match
    if tenant is None and name_hint:
        all_t = (await db.execute(
            select(Tenant).where(Tenant.landlord_id == landlord.id)
        )).scalars().all()
        matches = [t for t in all_t if name_hint in t.name.lower()]
        if len(matches) == 1:
            tenant = matches[0]
        elif len(matches) > 1:
            names = ", ".join(t.name for t in matches[:5])
            await _reply(
                landlord.phone_number,
                f"⚠️ Multiple tenants match _{name_hint}_: {names}.\nUse a number from *tenants* list.",
            )
            return

    if tenant is None:
        await _reply(
            landlord.phone_number,
            "⚠️ I couldn't identify which tenant.\nType *tenants* to see the list, then _message 1 ..._",
        )
        return

    prefix = f"💬 *Message from your landlord:*\n\n"
    try:
        await send_text_message(tenant.phone_number, prefix + text)
        await _reply(
            landlord.phone_number,
            f"✅ Sent to *{tenant.name}* (unit {tenant.unit_number}, {tenant.phone_number}).",
        )
        logger.info("Landlord→tenant message sent", from_=landlord.phone_number, to=tenant.phone_number)
    except Exception as exc:
        await _reply(landlord.phone_number, f"⚠️ Delivery failed: `{exc}`")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _reply(phone: str, text: str) -> None:
    try:
        result = await send_text_message(phone, text)
        if not result:
            logger.error("WhatsApp reply returned empty — token may be expired", phone=phone)
    except Exception as exc:
        logger.error("WhatsApp reply failed", phone=phone, error=str(exc))
        if "401" in str(exc):
            logger.error(
                "META_WHATSAPP_TOKEN expired — update .env and restart uvicorn "
                "(developers.facebook.com → WhatsApp → API Setup → Generate token)"
            )
