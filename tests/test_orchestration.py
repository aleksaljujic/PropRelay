"""
Tests for LangGraph maintenance orchestration.

Uses in-memory SQLite + MemorySaver checkpointer — no Redis/Postgres/Claude required.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.graph.builder import build_maintenance_graph
from app.graph.context import NodeContext, node_context
from app.graph.orchestrator import MaintenanceOrchestrator
from app.models.base import Base
from app.models.building import Building
from app.models.landlord import Landlord
from app.models.tenant import Tenant
from app.schemas.llm_outputs import DiagnosisResult, IntentClassification, IssueCategory, TenantIntent


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        landlord = Landlord(
            id=uuid.uuid4(),
            name="Test Landlord",
            email="landlord@test.com",
            phone_number="4916098765432",
        )
        building = Building(
            id=uuid.uuid4(),
            landlord_id=landlord.id,
            name="Test Building",
            address="Test St 1",
            city="Berlin",
            country="DE",
            whatsapp_number="4915111111111",
        )
        tenant = Tenant(
            id=uuid.uuid4(),
            building_id=building.id,
            landlord_id=landlord.id,
            name="Test Tenant",
            phone_number="4915123456789",
            unit_number="4B",
            language="en",
        )
        session.add_all([landlord, building, tenant])
        await session.commit()
        yield session, tenant

    await engine.dispose()


@pytest.fixture
def orchestrator_with_memory():
    graph = build_maintenance_graph(checkpointer=MemorySaver())
    orch = MaintenanceOrchestrator()
    orch._graph = graph
    return orch


@pytest.mark.asyncio
async def test_intent_routes_to_photo_request(db_session, orchestrator_with_memory):
    session, tenant = db_session
    orch = orchestrator_with_memory

    classification = IntentClassification(
        intent=TenantIntent.maintenance,
        confidence=0.95,
        summary="Leaking pipe",
        urgency="high",
    )

    with (
        patch("app.nodes.identify_intent.claude_service.classify_intent", AsyncMock(return_value=classification)),
        patch("app.nodes.request_photo.send_text_message", AsyncMock()),
        patch("app.nodes.request_photo.schedule_timeout", AsyncMock()),
    ):
        token = node_context.set(NodeContext(db=session))
        try:
            result = await orch.dispatch_tenant_message(
                tenant,
                {
                    "id": "msg1",
                    "type": "text",
                    "text": {"body": "The pipe is leaking"},
                },
                session,
            )
        finally:
            node_context.reset(token)

    assert result.get("intent") == "maintenance"
    assert result.get("ticket_id") is not None


@pytest.mark.asyncio
async def test_complaint_branch_completes(db_session, orchestrator_with_memory):
    session, tenant = db_session
    orch = orchestrator_with_memory

    classification = IntentClassification(
        intent=TenantIntent.complaint,
        confidence=0.9,
        summary="Noisy neighbors",
        urgency="low",
    )

    with (
        patch("app.nodes.identify_intent.claude_service.classify_intent", AsyncMock(return_value=classification)),
        patch("app.nodes.log_complaint.send_text_message", AsyncMock()),
    ):
        token = node_context.set(NodeContext(db=session))
        try:
            result = await orch.dispatch_tenant_message(
                tenant,
                {"id": "msg2", "type": "text", "text": {"body": "Neighbors too loud"}},
                session,
            )
        finally:
            node_context.reset(token)

    assert result.get("completed") is True
    assert result.get("intent") == "complaint"


@pytest.mark.asyncio
async def test_diagnosis_minor_routes_to_self_help(db_session, orchestrator_with_memory):
    session, tenant = db_session
    orch = orchestrator_with_memory

    maintenance = IntentClassification(
        intent=TenantIntent.maintenance,
        confidence=0.95,
        summary="Dripping tap",
        urgency="low",
    )
    diagnosis = DiagnosisResult(
        category=IssueCategory.plumbing,
        severity="minor",
        urgency="low",
        diagnosis="Loose tap washer",
        self_help_steps=["Turn off water", "Tighten the tap"],
        requires_professional=False,
    )

    with (
        patch("app.nodes.identify_intent.claude_service.classify_intent", AsyncMock(return_value=maintenance)),
        patch("app.nodes.request_photo.send_text_message", AsyncMock()),
        patch("app.nodes.request_photo.schedule_timeout", AsyncMock()),
        patch("app.nodes.diagnose_issue.download_media", AsyncMock(return_value=b"fake-image")),
        patch("app.nodes.diagnose_issue.claude_service.diagnose_image", AsyncMock(return_value=diagnosis)),
        patch("app.nodes.self_help.send_text_message", AsyncMock()),
    ):
        token = node_context.set(NodeContext(db=session))
        try:
            # Turn 1 — starts flow, interrupts for photo
            await orch.dispatch_tenant_message(
                tenant,
                {"id": "m1", "type": "text", "text": {"body": "Tap dripping"}},
                session,
            )
            # Turn 2 — send photo, resume
            result = await orch.dispatch_tenant_message(
                tenant,
                {
                    "id": "m2",
                    "type": "image",
                    "image": {"id": "img123", "mime_type": "image/jpeg"},
                },
                session,
            )
        finally:
            node_context.reset(token)

    assert result.get("severity") == "minor"
    assert result.get("completed") is True


@pytest.mark.asyncio
async def test_claude_fallback_intent_without_api_key():
    from app.services.claude_service import ClaudeService

    svc = ClaudeService()
    result = svc._fallback_intent("The water pipe is leaking")
    assert result.intent == TenantIntent.maintenance
