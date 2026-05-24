"""Vision AI diagnosis — Claude analyzes tenant photo."""
from __future__ import annotations

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.services.claude_service import claude_service
from app.services.ticket_service import get_ticket, sync_conversation_state, update_ticket_from_diagnosis
from app.services.whatsapp import download_media

logger = structlog.get_logger(__name__)


async def diagnose_issue(state: GraphState) -> dict:
    """
    Single step: download media, run Vision AI, persist diagnosis.

    Routing to self_help vs prepare_approval is handled by conditional edges.
    """
    ctx = get_node_context()
    db = ctx.db

    media_id = state.get("media_id")
    if not media_id:
        return {"error": "missing_media", "current_node": "diagnose_issue"}

    mime = state.get("media_mime") or "image/jpeg"
    description = state.get("message_text") or state.get("context", {}).get("intent_summary", "")

    try:
        image_bytes = await download_media(media_id)
    except Exception as exc:
        logger.error("Media download failed", error=str(exc))
        return {"error": f"media_download_failed: {exc}"}

    result = await claude_service.diagnose_image(
        image_bytes,
        mime_type=mime,
        description=description,
        language=state.get("language", "de"),
    )

    media_ref = f"meta://{media_id}"
    media_urls = list(state.get("media_urls") or [])
    if media_ref not in media_urls:
        media_urls.append(media_ref)

    if state.get("ticket_id"):
        ticket = await get_ticket(db, state["ticket_id"])
        if ticket:
            await update_ticket_from_diagnosis(
                db,
                ticket,
                category=result.category.value,
                urgency=result.urgency,
                ai_diagnosis=result.diagnosis,
                media_urls=media_urls,
                status=TicketStatus.triaged,
            )

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="diagnose_issue",
        ticket_id=state.get("ticket_id"),
        context={"severity": result.severity},
    )

    logger.info(
        "Diagnosis complete",
        severity=result.severity,
        category=result.category.value,
    )

    return {
        "current_node": "diagnose_issue",
        "severity": result.severity,
        "category": result.category.value,
        "urgency": result.urgency,
        "diagnosis": result.diagnosis,
        "ai_diagnosis_json": result.model_dump(),
        "media_urls": media_urls,
        "context": {"self_help_steps": result.self_help_steps},
    }
