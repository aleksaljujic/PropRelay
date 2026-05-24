from datetime import datetime
from uuid import UUID
from typing import Optional, Any

from pydantic import BaseModel

from app.models.ticket import (
    ConversationRole,
    LockedBy,
    TicketCategory,
    TicketStatus,
    TicketUrgency,
)


class TicketBase(BaseModel):
    description: str
    category: TicketCategory = TicketCategory.unknown
    urgency: TicketUrgency = TicketUrgency.medium


class TicketCreate(TicketBase):
    building_id: UUID
    tenant_id: UUID


class TicketUpdate(BaseModel):
    status: Optional[TicketStatus] = None
    category: Optional[TicketCategory] = None
    urgency: Optional[TicketUrgency] = None
    description: Optional[str] = None
    ai_diagnosis: Optional[str] = None
    media_urls: Optional[list[str]] = None
    landlord_approval: Optional[bool] = None
    contractor_id: Optional[UUID] = None
    locked_by: Optional[LockedBy] = None
    scheduled_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class TicketResponse(TicketBase):
    id: UUID
    building_id: UUID
    tenant_id: UUID
    contractor_id: Optional[UUID]
    status: TicketStatus
    ai_diagnosis: Optional[str]
    media_urls: Optional[list[str]]
    landlord_approval: Optional[bool]
    locked_by: Optional[LockedBy]
    locked_at: Optional[datetime]
    scheduled_at: Optional[datetime]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationStateResponse(BaseModel):
    id: UUID
    phone_number: str
    role: ConversationRole
    current_ticket_id: Optional[UUID]
    state: str
    context: Optional[dict[str, Any]]
    updated_at: datetime

    model_config = {"from_attributes": True}
