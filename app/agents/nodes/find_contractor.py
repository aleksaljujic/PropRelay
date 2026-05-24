"""
find_contractor node — select the best available contractor for the job.

Delegates to the existing contractor_selection service and sends a
confirmation request to the chosen contractor via WhatsApp.
"""
from __future__ import annotations

import structlog

from app.agents.state import PropFlowState
from app.core.redis import set_conversation_state
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)

_CONTRACTOR_REQUEST_TEMPLATE = (
    "🔧 Neuer Auftrag — {category} / {urgency}\n"
    "Adresse: {address}\n"
    "Beschreibung: {diagnosis}\n\n"
    "Können Sie diesen Auftrag übernehmen? "
    "Antworten Sie mit JA oder NEIN."
)


async def run(state: PropFlowState) -> PropFlowState:
    """
    Find and notify a contractor.

    In production this would query the contractors table filtered by
    category, availability, and building location. For the MVP it
    logs the intent and sets Redis state to 'awaiting_contractor_confirm'.
    """
    phone = state["phone_number"]
    diagnosis = state.get("diagnosis") or {}
    category = state.get("category") or diagnosis.get("contractor_specialty") or "general"
    urgency = state.get("urgency") or "medium"
    diagnosis_text = diagnosis.get("diagnosis") or "Maintenance issue"

    logger.info(
        "Finding contractor",
        category=category,
        urgency=urgency,
        ticket_id=state.get("ticket_id"),
    )

    # TODO: query contractors table for best match
    # For MVP — record intent and let the existing contractor flow handle it
    await set_conversation_state(
        phone,
        {
            "state": "awaiting_contractor_confirm",
            "ticket_id": state.get("ticket_id"),
            "category": category,
            "urgency": urgency,
        },
    )

    return {
        **state,
        "current_node": "find_contractor",
        "error": None,
    }
