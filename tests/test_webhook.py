"""
Tests for the WhatsApp webhook endpoints.

All tests run against the real FastAPI app with DB/Redis mocked via conftest.py.
"""
import pytest
from httpx import AsyncClient

from app.config import settings


# ---------------------------------------------------------------------------
# GET /api/v1/webhook  — hub verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_verification_success(client: AsyncClient):
    """Meta sends the correct verify_token → we echo the challenge."""
    response = await client.get(
        "/api/v1/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.meta_webhook_verify_token,
            "hub.challenge": "challenge_abc123",
        },
    )
    assert response.status_code == 200
    assert response.text == "challenge_abc123"


@pytest.mark.asyncio
async def test_webhook_verification_wrong_token(client: AsyncClient):
    """Wrong verify_token → 403."""
    response = await client.get(
        "/api/v1/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "definitely-wrong",
            "hub.challenge": "challenge_abc123",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webhook_verification_wrong_mode(client: AsyncClient):
    """hub.mode != 'subscribe' → 403."""
    response = await client.get(
        "/api/v1/webhook",
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": settings.meta_webhook_verify_token,
            "hub.challenge": "challenge_abc123",
        },
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/webhook  — incoming messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_receive_text_message(client: AsyncClient):
    """A standard text message payload returns 200 {"status": "ok"}."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "111"},
                            "messages": [
                                {
                                    "from": "+49151234567",
                                    "id": "wamid.abc123",
                                    "type": "text",
                                    "text": {"body": "Der Wasserhahn tropft."},
                                    "timestamp": "1700000000",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    response = await client.post("/api/v1/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_receive_image_message(client: AsyncClient):
    """An image message payload returns 200 {"status": "ok"}."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "+49151234567",
                                    "id": "wamid.img001",
                                    "type": "image",
                                    "image": {
                                        "id": "media_id_999",
                                        "mime_type": "image/jpeg",
                                        "caption": "broken pipe photo",
                                    },
                                    "timestamp": "1700000001",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    response = await client.post("/api/v1/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_receive_non_whatsapp_payload(client: AsyncClient):
    """Non-WhatsApp object type is silently ignored."""
    payload = {"object": "instagram", "entry": []}
    response = await client.post("/api/v1/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_receive_status_update(client: AsyncClient):
    """Delivery / read status updates return 200 {"status": "ok"}."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {
                                    "id": "wamid.abc123",
                                    "status": "delivered",
                                    "recipient_id": "+49151234567",
                                    "timestamp": "1700000002",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    response = await client.post("/api/v1/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Health endpoint returns 200 with expected keys."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "db" in data
    assert "redis" in data
    assert "version" in data
