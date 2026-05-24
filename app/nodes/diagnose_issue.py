"""Vision AI diagnosis — Claude Vision analyzes tenant photo."""
from __future__ import annotations

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.ticket import ConversationRole, TicketStatus
from app.schemas.llm_outputs import DiagnosisResult, IssueCategory
from app.services.ai_service import diagnose_from_image as _diagnose_from_image
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

    raw = await _diagnose_from_image(
        image_bytes,
        mime_type=mime,
        tenant_description=description,
        language=state.get("language", "de"),
    )
    # Map raw dict → validated DiagnosisResult schema
    self_fix_text = raw.get("self_fix_instructions") or ""
    self_help_steps = (
        [step.strip() for step in self_fix_text.split("\n") if step.strip()]
        if self_fix_text
        else []
    )
    cost = raw.get("estimated_cost_eur") or {}
    result = DiagnosisResult(
        category=IssueCategory(raw.get("contractor_specialty") or "general"),
        severity="serious" if raw.get("severity") in ("serious", "critical") else "minor",
        urgency=raw.get("urgency") or "medium",
        diagnosis=raw.get("diagnosis") or "See attached photo",
        root_cause=raw.get("root_cause"),
        safety_risk=raw.get("safety_risk") or "none",
        safety_notes=raw.get("safety_notes"),
        estimated_cost_min=cost.get("min"),
        estimated_cost_max=cost.get("max"),
        estimated_duration_minutes=raw.get("estimated_duration_minutes"),
        parts_needed=raw.get("parts_needed") or [],
        tools_needed=raw.get("tools_needed") or [],
        self_help_steps=self_help_steps,
        requires_professional=raw.get("recommended_action") != "self_fix",
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
