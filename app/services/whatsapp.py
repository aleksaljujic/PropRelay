"""
Meta WhatsApp Cloud API service.

All methods are async and use a shared httpx.AsyncClient per request.
See https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import structlog
import httpx

from app.config import settings

logger = structlog.get_logger(__name__)

_META_BASE = "https://graph.facebook.com"


def _base_url() -> str:
    return f"{_META_BASE}/{settings.meta_api_version}/{settings.meta_phone_number_id}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.meta_whatsapp_token}",
        "Content-Type": "application/json",
    }


async def send_text_message(phone: str, text: str) -> dict:
    """
    Send a plain-text WhatsApp message to a phone number.

    Args:
        phone: Recipient in E.164 format, e.g. "+49151234567"
        text:  Message body (max 4096 chars)

    Returns:
        Meta API response JSON
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{_base_url()}/messages",
            json=payload,
            headers=_headers(),
        )
        if response.is_error:
            logger.error("Meta API error", status=response.status_code, body=response.text, phone=phone)
        response.raise_for_status()
        data = response.json()
        logger.info("Text message sent", phone=phone, message_id=data.get("messages", [{}])[0].get("id"))
        return data


async def send_template_message(
    phone: str,
    template: str,
    params: list[str],
    language_code: str = "de",
) -> dict:
    """
    Send a pre-approved WhatsApp template message.

    Args:
        phone:         Recipient in E.164 format
        template:      Approved template name (e.g. "maintenance_update")
        params:        List of text parameters to inject into the template body
        language_code: BCP-47 language code (default: "de")

    Returns:
        Meta API response JSON
    """
    components: list[dict] = []
    if params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params],
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": language_code},
            "components": components,
        },
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{_base_url()}/messages",
            json=payload,
            headers=_headers(),
        )
        response.raise_for_status()
        data = response.json()
        logger.info("Template message sent", phone=phone, template=template)
        return data


async def download_media(media_id: str) -> bytes:
    """
    Download binary media (image, audio, video, document) from Meta servers.

    Args:
        media_id: The media ID received in the webhook payload

    Returns:
        Raw bytes of the media file
    """
    auth_headers = {"Authorization": f"Bearer {settings.meta_whatsapp_token}"}

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1 — resolve the temporary CDN URL
        meta_response = await client.get(
            f"{_META_BASE}/{settings.meta_api_version}/{media_id}",
            headers=auth_headers,
        )
        meta_response.raise_for_status()
        media_url: str = meta_response.json()["url"]

        # Step 2 — download the file
        media_response = await client.get(media_url, headers=auth_headers)
        media_response.raise_for_status()

        content = media_response.content
        logger.info(
            "Media downloaded",
            media_id=media_id,
            size_bytes=len(content),
            content_type=media_response.headers.get("content-type"),
        )
        return content
