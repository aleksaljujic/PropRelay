"""Ask tenant to describe their issue more clearly — used when intent is unknown."""
from __future__ import annotations

import structlog

from app.graph.state import GraphState
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)


async def clarify_intent(state: GraphState) -> dict:
    """
    Send a friendly clarification request to the tenant.
    Ends the current turn — next message starts a fresh invocation.
    """
    await send_text_message(
        state["phone"],
        "I'm not sure I understood your message. Could you describe the issue a bit more clearly?\n\n"
        "For example:\n"
        "• Maintenance problem: *'The heating is broken'* or *'Pipe is leaking'*\n"
        "• Rent question: *'How much do I owe this month?'*\n"
        "• Other request: *'I need a document'*",
    )
    logger.info("Clarification requested", phone=state.get("phone"))
    return {"current_node": "clarify_intent", "completed": True}
