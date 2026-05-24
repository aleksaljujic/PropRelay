"""
Shared pytest fixtures.

Mocks database and Redis so tests run without any live infrastructure.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def mock_infrastructure():
    """
    Patch DB engine, Redis, WhatsApp, and orchestrator so tests run without
    live infrastructure or background side effects.
    """
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=MagicMock())
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(return_value=mock_conn)
    mock_engine.dispose = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()
    mock_redis.zadd = AsyncMock()
    mock_redis.zrangebyscore = AsyncMock(return_value=[])

    with (
        patch("app.main.engine", mock_engine),
        patch("app.main.get_redis", AsyncMock(return_value=mock_redis)),
        patch("app.api.v1.webhook.get_tenant_by_phone", AsyncMock(return_value=None)),
        patch("app.api.v1.webhook.send_text_message", AsyncMock(return_value={})),
        patch("app.api.v1.webhook.orchestrator.dispatch_tenant_message", AsyncMock(return_value={})),
        patch("app.api.v1.webhook.lookup_landlord_by_phone", AsyncMock(return_value=None)),
        patch("app.graph.orchestrator.orchestrator.dispatch_tenant_message", AsyncMock(return_value={})),
        patch("app.graph.orchestrator.orchestrator.dispatch_landlord_message", AsyncMock(return_value=None)),
        patch("app.graph.orchestrator.orchestrator.dispatch_contractor_message", AsyncMock(return_value=None)),
        patch("app.workers.timeout_worker.start_timeout_worker"),
    ):
        yield


@pytest.fixture
async def client():
    """Async HTTP test client wired to the FastAPI app."""
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
