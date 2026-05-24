import uuid

from sqlalchemy import Boolean, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Landlord(Base, TimestampMixin):
    __tablename__ = "landlords"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="E.164 format e.g. +49151..."
    )
    whatsapp_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    language: Mapped[str] = mapped_column(
        String(10), default="de", nullable=False
    )

    # Relationships
    buildings: Mapped[list["Building"]] = relationship(  # noqa: F821
        "Building", back_populates="landlord", cascade="all, delete-orphan"
    )
    tenants: Mapped[list["Tenant"]] = relationship(  # noqa: F821
        "Tenant", back_populates="landlord"
    )
    contractors: Mapped[list["Contractor"]] = relationship(  # noqa: F821
        "Contractor", back_populates="landlord", cascade="all, delete-orphan"
    )
