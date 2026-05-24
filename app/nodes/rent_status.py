"""Rent status node — responds to tenant rent queries."""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.tenant import Tenant
from app.services.rent_service import format_status_for_tenant, get_rent_status
from app.services.whatsapp import send_text_message

logger = structlog.get_logger(__name__)


async def rent_status(state: GraphState) -> dict:
    ctx = get_node_context()
    db = ctx.db

    tenant = await db.scalar(
        select(Tenant).where(Tenant.id == uuid.UUID(state["tenant_id"]))
    )
    if not tenant:
        return {"completed": True, "current_node": "rent_status"}

    status = await get_rent_status(db, tenant)
    msg = format_status_for_tenant(status)
    await send_text_message(state["phone"], msg)

    logger.info("Rent status sent", phone=state["phone"], paid=status["paid"])
    return {"completed": True, "current_node": "rent_status"}
