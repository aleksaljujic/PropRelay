"""
diagnose node — download tenant image, run Claude Vision, update ticket.

Entry point after tenant sends a photo (routed here by the webhook when
conv_state.state == "awaiting_image").
"""
from __future__ import annotations

import structlog

from app.agents.state import PropFlowState
from app.core.redis import set_conversation_state
from app.services.ai_service import diagnose_from_image
from app.services.whatsapp import download_media, send_text_message

logger = structlog.get_logger(__name__)


async def run(state: PropFlowState) -> PropFlowState:
    """Download media, call Claude Vision, persist result."""
    phone = state["phone_number"]
    media_id = state.get("media_id")

    if not media_id:
        logger.error("diagnose: no media_id in state")
        await send_text_message(
            phone,
            "Sorry, we couldn't receive the image. Please try sending it again.",
        )
        return {
            **state,
            "current_node": "diagnose",
            "error": "missing_media_id",
        }

    # Download image from WhatsApp CDN
    try:
        image_bytes = await download_media(media_id)
    except Exception as exc:
        logger.error("diagnose: media download failed", error=str(exc))
        await send_text_message(
            phone,
            "We had trouble downloading your photo. Please try again.",
        )
        return {
            **state,
            "current_node": "diagnose",
            "error": f"media_download_failed: {exc}",
        }

    # Run Claude Vision diagnosis
    description = state.get("message_text") or "Maintenance issue reported by tenant"
    language = state.get("language", "de")
    mime_type = "image/jpeg"  # WhatsApp normalises images to JPEG

    try:
        diagnosis = await diagnose_from_image(
            image_bytes,
            mime_type=mime_type,
            tenant_description=description,
            language=language,
        )
    except Exception as exc:
        logger.error("diagnose: vision AI failed", error=str(exc))
        # Graceful degradation — treat as serious issue requiring professional
        diagnosis = {
            "diagnosis": "Unable to auto-diagnose. Manual review required.",
            "severity": "serious",
            "recommended_action": "contractor_needed",
            "self_fix_instructions": None,
            "estimated_cost_eur": {"min": 0, "max": 0},
            "contractor_specialty": "general",
        }

    logger.info(
        "Diagnosis complete",
        severity=diagnosis.get("severity"),
        recommended_action=diagnosis.get("recommended_action"),
    )

    # Persist result to Redis
    await set_conversation_state(
        phone,
        {
            "state": "diagnosed",
            "ticket_id": state.get("ticket_id"),
            "diagnosis": diagnosis,
            "urgency": state.get("urgency"),
        },
    )

    return {
        **state,
        "diagnosis": diagnosis,
        "current_node": "diagnose",
        "error": None,
    }
