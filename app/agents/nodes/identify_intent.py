"""
identify_intent node — classify tenant message via Claude Haiku.

Routing is deterministic from the output; Claude never picks the next node.
"""
from __future__ import annotations

import structlog

from app.agents.state import PropFlowState
from app.core.redis import set_conversation_state
from app.services.ai_service import classify_intent

logger = structlog.get_logger(__name__)


async def run(state: PropFlowState) -> PropFlowState:
    """Classify intent and persist result to Redis."""
    text = (state.get("message_text") or "").strip()
    if not text:
        logger.warning("identify_intent: empty message")
        return {
            **state,
            "intent": "unknown",
            "current_node": "identify_intent",
            "error": "empty_message",
        }

    result = await classify_intent(text, language=state.get("language", "de"))

    intent = result.get("intent", "unknown")
    category = result.get("category", "unknown")
    urgency = result.get("urgency", "medium")

    logger.info(
        "Intent classified",
        intent=intent,
        category=category,
        urgency=urgency,
        confidence=result.get("confidence"),
    )

    # Persist to Redis so the next message can resume the flow
    await set_conversation_state(
        state["phone_number"],
        {
            "state": "intent_classified",
            "ticket_id": state.get("ticket_id"),
            "intent": intent,
            "category": category,
            "urgency": urgency,
        },
    )

    return {
        **state,
        "intent": intent,
        "category": category,
        "urgency": urgency,
        "current_node": "identify_intent",
        "error": None,
    }
