"""
request_photo node — ask tenant to send a photo of the issue.

Halts the flow here; the graph resumes at 'diagnose' when the image arrives.
"""
from __future__ import annotations

import structlog

from app.agents.state import PropFlowState
from app.core.redis import set_conversation_state
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)

# Photo request messages keyed by language (fallback to English)
_PHOTO_MESSAGES: dict[str, str] = {
    "de": (
        "Danke für Ihre Nachricht! 📸\n\n"
        "Bitte schicken Sie uns ein Foto des Problems, "
        "damit wir die Situation besser einschätzen können."
    ),
    "en": (
        "Thank you for your message! 📸\n\n"
        "Please send us a photo of the issue "
        "so we can better assess the situation."
    ),
    "fr": (
        "Merci pour votre message ! 📸\n\n"
        "Veuillez nous envoyer une photo du problème "
        "pour que nous puissions mieux évaluer la situation."
    ),
}


async def run(state: PropFlowState) -> PropFlowState:
    """Send photo-request message and set Redis state to awaiting_image."""
    phone = state["phone_number"]
    language = state.get("language", "de")

    msg = _PHOTO_MESSAGES.get(language, _PHOTO_MESSAGES["en"])
    await send_text_message(phone, msg)

    logger.info("Sending photo request to tenant...", phone=phone)

    # Mark Redis state — webhook will route the next image message to diagnose
    await set_conversation_state(
        phone,
        {
            "state": "awaiting_image",
            "ticket_id": state.get("ticket_id"),
            "intent": state.get("intent"),
            "category": state.get("category"),
            "urgency": state.get("urgency"),
        },
    )

    logger.info("Redis state set: awaiting_image", phone=phone)

    return {
        **state,
        "current_node": "request_photo",
        "error": None,
    }
