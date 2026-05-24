"""RentPayment — tracks monthly rent records per tenant."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class RentPayment(Base, TimestampMixin):
    __tablename__ = "rent_payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_year", "period_month", name="uq_tenant_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–12
    amount_due: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    amount_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationship
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="rent_payments")  # noqa: F821
