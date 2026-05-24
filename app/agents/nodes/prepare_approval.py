"""
prepare_approval node — build landlord approval request from diagnosis.

Assembles all ticket details into a concise, actionable summary ready
to be sent to the landlord by the notify_landlord node.
"""
from __future__ import annotations

import structlog

from app.agents.state import PropFlowState
from app.core.redis import set_conversation_state

logger = structlog.get_logger(__name__)


async def run(state: PropFlowState) -> PropFlowState:
    """Assemble approval payload and persist to Redis."""
    phone = state["phone_number"]
    diagnosis = state.get("diagnosis") or {}

    # Build a human-readable urgency + category label for the landlord message
    urgency = state.get("urgency") or diagnosis.get("urgency") or "medium"
    category = state.get("category") or diagnosis.get("contractor_specialty") or "general"
    estimated_cost = diagnosis.get("estimated_cost_eur") or {"min": 0, "max": 0}
    diagnosis_text = diagnosis.get("diagnosis", "See attached photo")

    approval_payload = {
        "phone_number": phone,
        "tenant_id": state.get("tenant_id"),
        "ticket_id": state.get("ticket_id"),
        "category": category,
        "urgency": urgency,
        "diagnosis": diagnosis_text,
        "estimated_cost": estimated_cost,
        "recommended_action": diagnosis.get("recommended_action", "contractor_needed"),
    }

    logger.info(
        "Approval payload prepared",
        ticket_id=state.get("ticket_id"),
        urgency=urgency,
        category=category,
    )

    await set_conversation_state(
        phone,
        {
            "state": "approval_pending",
            "ticket_id": state.get("ticket_id"),
            "approval_payload": approval_payload,
        },
    )

    return {
        **state,
        "current_node": "prepare_approval",
        "urgency": urgency,
        "category": category,
        "error": None,
        # Store approval payload in state for notify_landlord
        "diagnosis": {**diagnosis, "_approval_payload": approval_payload},
    }
