"""
Confirm diagnosis with tenant before escalating to landlord.

Tenant sees what AI found and can:
  - Reply YES / ok / correct → proceed as-is
  - Reply with their own description → replace / enrich diagnosis
"""
from __future__ import annotations

import structlog
from langgraph.types import interrupt
from sqlalchemy import select

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, ConversationState
from app.services.ticket_service import sync_conversation_state
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)

_CONFIRM_WORDS = {"yes", "y", "ok", "correct", "da", "tačno", "tacno", "yep", "sure", "ja", "👍", "✅"}

URGENCY_EMOJI = {"emergency": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢"}
CATEGORY_EMOJI = {
    "plumbing": "🔧", "electrical": "⚡", "hvac": "❄️",
    "structural": "🏗️", "appliance": "🔌", "general": "🔨",
}


async def _confirm_prompt_already_sent(db, phone: str, ticket_id: str | None) -> bool:
    if not ticket_id:
        return False
    row = await db.scalar(select(ConversationState).where(ConversationState.phone_number == phone))
    if not row:
        return False
    ctx = row.context or {}
    return ctx.get("confirm_prompt_sent") == ticket_id


def _parse_tenant_reply(reply: str, diagnosis: str, context: dict) -> dict:
    if reply.lower() in _CONFIRM_WORDS:
        return {
            "current_node": "confirm_with_tenant",
            "tenant_confirmed": True,
            "resume_value": None,
        }
    enriched = f"{diagnosis}\nTenant adds: {reply}"
    return {
        "current_node": "confirm_with_tenant",
        "tenant_confirmed": True,
        "diagnosis": enriched,
        "context": {**context, "tenant_note": reply},
        "resume_value": None,
    }


async def confirm_with_tenant(state: GraphState) -> dict:
    ctx = get_node_context()
    db = ctx.db
    ticket_id = state.get("ticket_id")
    context = state.get("context") or {}

    resume = state.get("resume_value")
    if resume is not None:
        reply = str(resume).strip()
        if reply.lower() in _CONFIRM_WORDS:
            await send_text_message(
                state["phone"],
                "Thanks — forwarded to your landlord for approval.",
            )
            logger.info("Tenant confirmed diagnosis", phone=state["phone"])
        else:
            logger.info("Tenant updated diagnosis", phone=state["phone"])
        return _parse_tenant_reply(reply, state.get("diagnosis", ""), context)

    if await _confirm_prompt_already_sent(db, state["phone"], ticket_id):
        logger.info("Confirm prompt already sent — waiting for tenant reply", phone=state["phone"])
        reply = interrupt({"awaiting": "tenant_confirmation"})
        reply_text = str(reply).strip() if reply else ""
        if reply_text.lower() in _CONFIRM_WORDS:
            await send_text_message(
                state["phone"],
                "Thanks — forwarded to your landlord for approval.",
            )
        return _parse_tenant_reply(reply_text, state.get("diagnosis", ""), context)

    diagnosis = state.get("diagnosis", "Issue detected")
    severity = state.get("severity", "unknown")
    urgency = state.get("urgency", "medium")
    category = state.get("category", "general")

    urgency_emoji = URGENCY_EMOJI.get(urgency, "🟡")
    category_emoji = CATEGORY_EMOJI.get(category, "🔨")

    msg = (
        f"{urgency_emoji} *Here's what we identified:*\n\n"
        f"{category_emoji} Category: *{category.upper()}*\n"
        f"Severity: *{severity.upper()}*\n\n"
        f"📋 {diagnosis}\n\n"
        f"Is this correct?\n"
        f"• Reply *YES* to contact your landlord\n"
        f"• Or describe what's actually wrong and we'll update it"
    )

    await send_text_message(state["phone"], msg)

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="confirm_with_tenant",
        ticket_id=ticket_id,
        context={"awaiting": "tenant_confirmation", "confirm_prompt_sent": ticket_id},
    )

    logger.info("Diagnosis sent to tenant for confirmation", phone=state["phone"])

    reply = interrupt({"awaiting": "tenant_confirmation"})
    reply_text = str(reply).strip() if reply else ""
    if reply_text.lower() in _CONFIRM_WORDS:
        await send_text_message(
            state["phone"],
            "Thanks — forwarded to your landlord for approval.",
        )
    return _parse_tenant_reply(reply_text, diagnosis, context)
