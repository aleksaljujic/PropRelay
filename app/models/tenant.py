import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    building_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False
    )
    landlord_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("landlords.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="E.164 format — primary WhatsApp identifier",
    )
    unit_number: Mapped[str] = mapped_column(
        String(20), nullable=False, comment='e.g. "4B"'
    )
    rent_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    rent_due_day: Mapped[Optional[int]] = mapped_column(
        Integer, comment="Day of month rent is due (1-28)"
    )
    lease_start: Mapped[Optional[date]] = mapped_column(Date)
    lease_end: Mapped[Optional[date]] = mapped_column(Date)
    language: Mapped[str] = mapped_column(
        String(10), default="de", nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    building: Mapped["Building"] = relationship(  # noqa: F821
        "Building", back_populates="tenants"
    )
    landlord: Mapped["Landlord"] = relationship(  # noqa: F821
        "Landlord", back_populates="tenants"
    )
    tickets: Mapped[list["Ticket"]] = relationship(  # noqa: F821
        "Ticket", back_populates="tenant"
    )
