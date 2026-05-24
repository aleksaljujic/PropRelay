"""
Confirm diagnosis with tenant before escalating to landlord.

Tenant sees what AI found and can:
  - Reply YES / ok / correct → proceed as-is
  - Reply with their own description → replace / enrich diagnosis
"""
from __future__ import annotations

import structlog
from langgraph.types import interrupt

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole
from app.services.ticket_service import sync_conversation_state
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)

_CONFIRM_WORDS = {"yes", "ok", "correct", "da", "tačno", "tacno", "yep", "sure", "👍", "✅"}

URGENCY_EMOJI = {"emergency": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢"}
CATEGORY_EMOJI = {
    "plumbing": "🔧", "electrical": "⚡", "hvac": "❄️",
    "structural": "🏗️", "appliance": "🔌", "general": "🔨",
}


async def confirm_with_tenant(state: GraphState) -> dict:
    ctx = get_node_context()
    db = ctx.db

    # ── Resume path — tenant replied ──────────────────────────────────────────
    resume = state.get("resume_value")
    if resume is not None:
        reply = str(resume).strip()
        if reply.lower() in _CONFIRM_WORDS or len(reply) < 4:
            # Confirmed as-is
            logger.info("Tenant confirmed diagnosis", phone=state["phone"])
            return {
                "current_node": "confirm_with_tenant",
                "tenant_confirmed": True,
                "resume_value": None,
            }
        else:
            # Tenant corrected / added info — enrich diagnosis
            original = state.get("diagnosis", "")
            enriched = f"{original}\nTenant adds: {reply}"
            logger.info("Tenant updated diagnosis", phone=state["phone"])
            return {
                "current_node": "confirm_with_tenant",
                "tenant_confirmed": True,
                "diagnosis": enriched,
                "context": {**state.get("context", {}), "tenant_note": reply},
                "resume_value": None,
            }

    # ── First pass — send diagnosis summary to tenant ─────────────────────────
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
        ticket_id=state.get("ticket_id"),
        context={"awaiting": "tenant_confirmation"},
    )

    logger.info("Diagnosis sent to tenant for confirmation", phone=state["phone"])

    # Interrupt — wait for tenant reply
    reply = interrupt({"awaiting": "tenant_confirmation"})
    reply_text = str(reply).strip() if reply else ""

    if reply_text.lower() in _CONFIRM_WORDS or len(reply_text) < 4:
        return {"current_node": "confirm_with_tenant", "tenant_confirmed": True, "resume_value": None}

    enriched = f"{state.get('diagnosis', '')}\nTenant adds: {reply_text}"
    return {
        "current_node": "confirm_with_tenant",
        "tenant_confirmed": True,
        "diagnosis": enriched,
        "context": {**state.get("context", {}), "tenant_note": reply_text},
        "resume_value": None,
    }
