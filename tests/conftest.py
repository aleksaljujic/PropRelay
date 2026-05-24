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
    Patch DB engine and Redis client at the module level so that the FastAPI
    lifespan does not require real PostgreSQL / Redis connections.
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

    with (
        patch("app.main.engine", mock_engine),
        patch("app.main.get_redis", AsyncMock(return_value=mock_redis)),
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
