import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Contractor(Base, TimestampMixin):
    __tablename__ = "contractors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    landlord_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("landlords.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="E.164 format"
    )
    specialties: Mapped[Optional[list[str]]] = mapped_column(
        JSON,
        default=list,
        comment='e.g. ["plumbing", "electrical", "hvac", "general"]',
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, comment='e.g. "only available Tuesday-Thursday"'
    )
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en",
        comment="BCP-47 language code for translated WhatsApp messages",
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    landlord: Mapped["Landlord"] = relationship(  # noqa: F821
        "Landlord", back_populates="contractors"
    )
    tickets: Mapped[list["Ticket"]] = relationship(  # noqa: F821
        "Ticket", back_populates="contractor"
    )
