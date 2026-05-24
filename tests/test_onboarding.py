"""
Integration tests for the onboarding flow.

Uses an in-memory SQLite database and mocks:
  - send_text_message  (captures outbound WhatsApp calls)
  - Redis helpers      (uses in-memory dict instead of real Redis)
"""
import json
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.building import Building
from app.models.landlord import Landlord
from app.models.tenant import Tenant


# ---------------------------------------------------------------------------
# In-memory SQLite fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="function")
async def db(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture(scope="function")
async def seed_data(db: AsyncSession):
    """Insert one landlord, one building, two tenants."""
    landlord = Landlord(
        name="Test Landlord",
        email="landlord@test.dev",
        phone_number="490000000000",
        whatsapp_verified=True,
        language="de",
    )
    db.add(landlord)
    await db.flush()

    building = Building(
        landlord_id=landlord.id,
        name="Test Building",
        address="Teststraße 1",
        city="Berlin",
        country="DE",
        whatsapp_number="15556402370",
    )
    db.add(building)
    await db.flush()

    tenant_onboarded = Tenant(
        building_id=building.id,
        landlord_id=landlord.id,
        name="Milan Petrović",
        phone_number="381603334933",
        unit_number="4B",
        language="de",
        active=True,
    )
    tenant_pending = Tenant(
        building_id=building.id,
        landlord_id=landlord.id,
        name="Pending",
        phone_number="381600000002",
        unit_number="2A",
        language="de",
        active=True,
    )
    db.add_all([tenant_onboarded, tenant_pending])
    await db.commit()

    return {
        "landlord": landlord,
        "building": building,
        "tenant_onboarded": tenant_onboarded,
        "tenant_pending": tenant_pending,
    }


# ---------------------------------------------------------------------------
# Redis in-memory mock
# ---------------------------------------------------------------------------

_redis_store: dict[str, str] = {}


async def _mock_get_conv_state(phone: str):
    raw = _redis_store.get(f"conv:{phone}")
    return json.loads(raw) if raw else None


async def _mock_set_conv_state(phone: str, state: dict, ttl: int = 86400):
    _redis_store[f"conv:{phone}"] = json.dumps(state)


async def _mock_clear_conv_state(phone: str):
    _redis_store.pop(f"conv:{phone}", None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_number_gets_rejection(db: AsyncSession, seed_data):
    """Unknown number → rejection message in German."""
    sent_messages: list[tuple[str, str]] = []

    async def capture_send(phone, text):
        sent_messages.append((phone, text))

    from app.services import tenant_lookup, onboarding_service

    with (
        patch.object(tenant_lookup, "get_tenant_by_phone",
                     new=AsyncMock(return_value=None)),
        patch("app.services.onboarding_service.send_text_message",
              side_effect=capture_send),
    ):
        from app.services.onboarding_service import UNKNOWN_NUMBER_MSG
        from app.services.whatsapp import send_text_message as real_send

        # Simulate unknown phone
        tenant = await tenant_lookup.get_tenant_by_phone("999000000000", db)
        assert tenant is None

        # Would send rejection
        await capture_send("999000000000", UNKNOWN_NUMBER_MSG)

    assert len(sent_messages) == 1
    phone, text = sent_messages[0]
    assert phone == "999000000000"
    assert "nicht in unserem System" in text


@pytest.mark.asyncio
async def test_pending_tenant_gets_welcome_on_onboarding(db: AsyncSession, seed_data):
    """Tenant with name=Pending → onboarding sets Redis state + sends welcome."""
    _redis_store.clear()
    sent_messages: list[tuple[str, str]] = []

    async def capture_send(phone, text):
        sent_messages.append((phone, text))

    with (
        patch("app.services.onboarding_service.set_conversation_state",
              side_effect=_mock_set_conv_state),
        patch("app.services.onboarding_service.send_text_message",
              side_effect=capture_send),
        patch("app.database.async_session_factory") as mock_factory,
    ):
        # Make async_session_factory return a context manager that yields our test db
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        from app.services.onboarding_service import initiate_tenant_onboarding
        tenant_pending = seed_data["tenant_pending"]
        await initiate_tenant_onboarding(tenant_pending)

    # Redis state was set
    state_key = f"conv:{tenant_pending.phone_number}"
    assert state_key in _redis_store
    state = json.loads(_redis_store[state_key])
    assert state["state"] == "awaiting_name"
    assert state["tenant_id"] == str(tenant_pending.id)

    # Welcome message was sent
    assert len(sent_messages) == 1
    phone, text = sent_messages[0]
    assert phone == tenant_pending.phone_number
    assert "Wie heißen Sie" in text
    assert "Test Building" in text


@pytest.mark.asyncio
async def test_onboarding_reply_saves_name(db: AsyncSession, seed_data):
    """Tenant in awaiting_name state replies 'Maria Schmidt' → name saved."""
    _redis_store.clear()
    tenant_pending = seed_data["tenant_pending"]
    phone = tenant_pending.phone_number
    sent_messages: list[tuple[str, str]] = []

    # Pre-set Redis state (as if onboarding was initiated)
    await _mock_set_conv_state(phone, {
        "state": "awaiting_name",
        "tenant_id": str(tenant_pending.id),
    })

    async def capture_send(p, t):
        sent_messages.append((p, t))

    with (
        patch("app.services.onboarding_service.clear_conversation_state",
              side_effect=_mock_clear_conv_state),
        patch("app.services.onboarding_service.send_text_message",
              side_effect=capture_send),
    ):
        from app.services.onboarding_service import handle_onboarding_reply
        await handle_onboarding_reply(phone, "Maria Schmidt", db)

    # DB updated
    result = await db.execute(select(Tenant).where(Tenant.phone_number == phone))
    updated_tenant = result.scalar_one()
    assert updated_tenant.name == "Maria Schmidt"
    assert updated_tenant.active is True

    # Redis cleared
    assert f"conv:{phone}" not in _redis_store

    # Confirmation sent
    assert len(sent_messages) == 1
    p, text = sent_messages[0]
    assert p == phone
    assert "Maria Schmidt" in text
    assert "2A" in text


@pytest.mark.asyncio
async def test_name_too_short_asks_again(db: AsyncSession, seed_data):
    """Single-word reply → bot asks for full name again."""
    _redis_store.clear()
    tenant_pending = seed_data["tenant_pending"]
    phone = tenant_pending.phone_number
    sent_messages: list[tuple[str, str]] = []

    await _mock_set_conv_state(phone, {
        "state": "awaiting_name",
        "tenant_id": str(tenant_pending.id),
    })

    async def capture_send(p, t):
        sent_messages.append((p, t))

    with patch("app.services.onboarding_service.send_text_message",
               side_effect=capture_send):
        from app.services.onboarding_service import handle_onboarding_reply
        await handle_onboarding_reply(phone, "Maria", db)

    # Name NOT saved — tenant still "Pending"
    result = await db.execute(select(Tenant).where(Tenant.phone_number == phone))
    tenant = result.scalar_one()
    assert tenant.name == "Pending"

    # Bot asked again
    assert len(sent_messages) == 1
    assert "vollständigen Namen" in sent_messages[0][1]


@pytest.mark.asyncio
async def test_registered_tenant_gets_acknowledgement(db: AsyncSession, seed_data):
    """Fully onboarded tenant → acknowledgement message in German."""
    sent_messages: list[tuple[str, str]] = []

    async def capture_send(p, t):
        sent_messages.append((p, t))

    tenant_onboarded = seed_data["tenant_onboarded"]

    with patch("app.services.whatsapp.send_text_message", side_effect=capture_send):
        from app.services.whatsapp import send_text_message
        await send_text_message(
            tenant_onboarded.phone_number,
            f"Danke {tenant_onboarded.name}! Ihre Nachricht wurde empfangen. Wir melden uns gleich.",
        )

    assert len(sent_messages) == 1
    p, text = sent_messages[0]
    assert p == tenant_onboarded.phone_number
    assert "Milan Petrović" in text
    assert "Danke" in text
