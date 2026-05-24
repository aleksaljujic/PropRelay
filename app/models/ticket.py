import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Enum as SAEnum, ForeignKey,
    JSON, String, Text, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class TicketStatus(str, enum.Enum):
    new = "new"
    triaged = "triaged"
    awaiting_landlord = "awaiting_landlord"
    approved = "approved"
    dispatched = "dispatched"
    scheduled = "scheduled"
    completed = "completed"
    rejected = "rejected"
    self_resolved = "self_resolved"


class TicketCategory(str, enum.Enum):
    plumbing = "plumbing"
    electrical = "electrical"
    hvac = "hvac"
    structural = "structural"
    appliance = "appliance"
    general = "general"
    complaint = "complaint"
    admin = "admin"
    unknown = "unknown"


class TicketUrgency(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    emergency = "emergency"


class LockedBy(str, enum.Enum):
    whatsapp = "whatsapp"
    dashboard = "dashboard"


class ConversationRole(str, enum.Enum):
    tenant = "tenant"
    landlord = "landlord"
    contractor = "contractor"


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    building_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("buildings.id"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False
    )
    contractor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("contractors.id"), nullable=True
    )

    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, native_enum=False),
        nullable=False,
        default=TicketStatus.new,
    )
    category: Mapped[TicketCategory] = mapped_column(
        SAEnum(TicketCategory, native_enum=False),
        nullable=False,
        default=TicketCategory.unknown,
    )
    urgency: Mapped[TicketUrgency] = mapped_column(
        SAEnum(TicketUrgency, native_enum=False),
        nullable=False,
        default=TicketUrgency.medium,
    )

    description: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Tenant's original message"
    )
    ai_diagnosis: Mapped[Optional[str]] = mapped_column(
        Text, comment="Vision AI analysis result"
    )
    media_urls: Mapped[Optional[list[str]]] = mapped_column(
        JSON, default=list, comment="Image/video URLs stored on our server"
    )

    landlord_approval: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, comment="None=pending, True=approved, False=rejected"
    )
    locked_by: Mapped[Optional[LockedBy]] = mapped_column(
        SAEnum(LockedBy, native_enum=False), nullable=True, comment="Optimistic locking"
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When contractor is coming"
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    building: Mapped["Building"] = relationship("Building", back_populates="tickets")  # noqa: F821
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="tickets")  # noqa: F821
    contractor: Mapped[Optional["Contractor"]] = relationship(  # noqa: F821
        "Contractor", back_populates="tickets"
    )


class ConversationState(Base):
    """Redis-backed conversation state, also persisted to DB for recovery."""

    __tablename__ = "conversation_states"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    phone_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="The sender's phone number — primary key for lookups",
    )
    role: Mapped[ConversationRole] = mapped_column(
        SAEnum(ConversationRole, native_enum=False), nullable=False
    )
    current_ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("tickets.id"), nullable=True
    )
    state: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment='LangGraph node name, e.g. "awaiting_image", "awaiting_approval"',
    )
    context: Mapped[Optional[dict]] = mapped_column(
        JSON, default=dict, comment="Arbitrary state data"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
