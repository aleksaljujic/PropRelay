"""
Ticket lifecycle service — DB persistence for orchestration nodes.

Nodes create and update tickets; this service keeps SQLAlchemy details
out of the graph layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.ticket import (
    ConversationRole,
    ConversationState,
    LockedBy,
    Ticket,
    TicketCategory,
    TicketStatus,
    TicketUrgency,
)

logger = structlog.get_logger(__name__)


async def create_ticket(
    db: AsyncSession,
    tenant: Tenant,
    description: str,
    category: str = "unknown",
    urgency: str = "medium",
) -> Ticket:
    """Create a new maintenance ticket for a tenant."""
    ticket = Ticket(
        building_id=tenant.building_id,
        tenant_id=tenant.id,
        description=description,
        category=TicketCategory(category) if category in TicketCategory.__members__ else TicketCategory.unknown,
        urgency=TicketUrgency(urgency) if urgency in TicketUrgency.__members__ else TicketUrgency.medium,
        status=TicketStatus.new,
        media_urls=[],
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    logger.info("Ticket created", ticket_id=str(ticket.id), tenant_id=str(tenant.id))
    return ticket


async def get_ticket(db: AsyncSession, ticket_id: str | uuid.UUID) -> Ticket | None:
    result = await db.execute(select(Ticket).where(Ticket.id == uuid.UUID(str(ticket_id))))
    return result.scalar_one_or_none()


async def update_ticket_from_diagnosis(
    db: AsyncSession,
    ticket: Ticket,
    *,
    category: str,
    urgency: str,
    ai_diagnosis: str,
    media_urls: list[str] | None = None,
    status: TicketStatus = TicketStatus.triaged,
) -> Ticket:
    ticket.category = TicketCategory(category) if category in TicketCategory.__members__ else TicketCategory.unknown
    ticket.urgency = TicketUrgency(urgency) if urgency in TicketUrgency.__members__ else TicketUrgency.medium
    ticket.ai_diagnosis = ai_diagnosis
    if media_urls is not None:
        ticket.media_urls = media_urls
    ticket.status = status
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def set_ticket_status(
    db: AsyncSession,
    ticket: Ticket,
    status: TicketStatus,
    *,
    landlord_approval: bool | None = None,
    contractor_id: uuid.UUID | None = None,
    resolved_at: datetime | None = None,
) -> Ticket:
    ticket.status = status
    if landlord_approval is not None:
        ticket.landlord_approval = landlord_approval
    if contractor_id is not None:
        ticket.contractor_id = contractor_id
    if resolved_at is not None:
        ticket.resolved_at = resolved_at
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def acquire_whatsapp_lock(db: AsyncSession, ticket: Ticket) -> bool:
    """Mark ticket as locked by WhatsApp orchestration."""
    if ticket.locked_by and ticket.locked_by != LockedBy.whatsapp:
        return False
    ticket.locked_by = LockedBy.whatsapp
    ticket.locked_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def release_whatsapp_lock(db: AsyncSession, ticket: Ticket) -> None:
    ticket.locked_by = None
    ticket.locked_at = None
    await db.commit()


async def sync_conversation_state(
    db: AsyncSession,
    *,
    phone: str,
    role: ConversationRole,
    state: str,
    ticket_id: str | uuid.UUID | None = None,
    context: dict | None = None,
) -> None:
    """Mirror Redis graph state to the conversation_states table."""
    ticket_uuid: uuid.UUID | None = None
    if ticket_id is not None:
        ticket_uuid = ticket_id if isinstance(ticket_id, uuid.UUID) else uuid.UUID(str(ticket_id))

    result = await db.execute(
        select(ConversationState).where(ConversationState.phone_number == phone)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ConversationState(
            phone_number=phone,
            role=role,
            state=state,
            current_ticket_id=ticket_uuid,
            context=context or {},
        )
        db.add(row)
    else:
        row.role = role
        row.state = state
        row.current_ticket_id = ticket_uuid
        row.context = context or {}
    await db.commit()
