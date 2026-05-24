"""
notify_landlord node — send the approval request to the landlord.

The graph halts here; the landlord's JA/NEIN reply is handled by the
existing orchestrator (app/graph/orchestrator.py) which resumes the flow.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import PropFlowState
from app.core.redis import get_conversation_state, set_conversation_state
from app.models.landlord import Landlord
from app.services.ai_service import generate_landlord_approval_message
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)


async def run(state: PropFlowState) -> PropFlowState:
    """Send approval message to landlord and wait for their reply."""
    phone = state["phone_number"]
    diagnosis = state.get("diagnosis") or {}

    # Pull approval payload (set by prepare_approval) or fall back to state fields
    approval = diagnosis.get("_approval_payload") or {}
    tenant_name = approval.get("tenant_name") or state.get("tenant_id", "Tenant")
    unit = approval.get("unit") or "—"
    category = state.get("category") or approval.get("category") or "general"
    urgency = state.get("urgency") or approval.get("urgency") or "medium"
    diagnosis_text = diagnosis.get("diagnosis") or approval.get("diagnosis") or ""
    estimated_cost = diagnosis.get("estimated_cost_eur") or approval.get("estimated_cost") or {}

    # Landlord phone comes from Redis state (set during onboarding)
    conv_state = await get_conversation_state(phone) or {}
    landlord_phone = conv_state.get("landlord_phone") or state.get("landlord_id", "")

    if not landlord_phone:
        logger.warning("notify_landlord: no landlord_phone in state", phone=phone)
        return {
            **state,
            "current_node": "notify_landlord",
            "error": "missing_landlord_phone",
        }

    # Build and send the approval message
    msg = await generate_landlord_approval_message(
        tenant_name=tenant_name,
        unit=unit,
        category=category,
        urgency=urgency,
        diagnosis=diagnosis_text,
        estimated_cost=estimated_cost,
    )

    await send_text_message(landlord_phone, msg)
    logger.info("Landlord notified", landlord_phone=landlord_phone, ticket_id=state.get("ticket_id"))

    # Update Redis — graph waits here for landlord's JA/NEIN
    await set_conversation_state(
        phone,
        {
            **conv_state,
            "state": "awaiting_landlord_approval",
            "ticket_id": state.get("ticket_id"),
            "landlord_phone": landlord_phone,
        },
    )

    return {
        **state,
        "current_node": "notify_landlord",
        "error": None,
    }
