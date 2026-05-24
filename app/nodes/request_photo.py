"""Ask tenant for a photo — pauses graph until image arrives."""
from __future__ import annotations

import structlog
from langgraph.types import interrupt

from app.config import settings
from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole
from app.services.ticket_service import sync_conversation_state
from app.services.whatsapp import send_text_message
from app.workers.timeout_scheduler import schedule_timeout, TimeoutKind

logger = structlog.get_logger(__name__)

_PHOTO_PROMPT = (
    "Thanks for reporting this. Please send a clear photo of the issue "
    "so we can assess urgency and next steps."
)


async def request_photo(state: GraphState) -> dict:
    """
    One interaction: request photo OR pass through if media already present.

    Uses LangGraph interrupt() — graph pauses until tenant sends an image.
    """
    ctx = get_node_context()
    db = ctx.db
    phone = state["phone"]

    # Resume path — tenant sent an image
    if state.get("media_id"):
        logger.info("Photo received", media_id=state["media_id"])
        await sync_conversation_state(
            db,
            phone=phone,
            role=ConversationRole.tenant,
            state="diagnose_issue",
            ticket_id=state.get("ticket_id"),
        )
        return {"current_node": "request_photo", "awaiting": None}

    # First visit — send prompt and pause
    await send_text_message(phone, _PHOTO_PROMPT)

    if state.get("ticket_id"):
        await schedule_timeout(
            kind=TimeoutKind.PHOTO_REMINDER,
            thread_id=state["thread_id"],
            ticket_id=state["ticket_id"],
            phone=phone,
            delay_seconds=settings.timeout_photo_reminder_seconds,
        )

    await sync_conversation_state(
        db,
        phone=phone,
        role=ConversationRole.tenant,
        state="request_photo",
        ticket_id=state.get("ticket_id"),
        context={"awaiting": "photo"},
    )

    # Pause graph — resumes with media payload from orchestrator
    resume_data = interrupt({"awaiting": "photo", "ticket_id": state.get("ticket_id")})
    if isinstance(resume_data, dict) and resume_data.get("media_id"):
        return {
            "current_node": "request_photo",
            "awaiting": None,
            "media_id": resume_data["media_id"],
            "media_mime": resume_data.get("media_mime", "image/jpeg"),
            "message_text": resume_data.get("message_text", ""),
        }
    return {"current_node": "request_photo", "awaiting": "photo"}
