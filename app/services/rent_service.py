"""
Rent status helpers.

Calculates whether the current month's rent is paid, overdue, or upcoming.
Landlords mark payments via WhatsApp command; tenants query their status.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rent_payment import RentPayment
from app.models.tenant import Tenant


async def get_or_create_record(db: AsyncSession, tenant: Tenant) -> RentPayment:
    """Return this month's rent record, creating it if it doesn't exist yet."""
    today = date.today()
    record = await db.scalar(
        select(RentPayment).where(
            RentPayment.tenant_id == tenant.id,
            RentPayment.period_year == today.year,
            RentPayment.period_month == today.month,
        )
    )
    if record:
        return record

    due_day = min(tenant.rent_due_day or 1, 28)
    due_date = today.replace(day=due_day)
    amount = tenant.rent_amount or Decimal("0.00")

    record = RentPayment(
        tenant_id=tenant.id,
        period_year=today.year,
        period_month=today.month,
        amount_due=amount,
        due_date=due_date,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_rent_status(db: AsyncSession, tenant: Tenant) -> dict:
    """
    Return a dict describing the tenant's current rent situation.

    Keys:
      paid         bool
      amount_due   Decimal
      amount_paid  Decimal | None
      balance      Decimal  (0 if paid in full, positive = still owed)
      due_date     date
      days_overdue int  (0 if not overdue)
      paid_at      datetime | None
      period       str  e.g. "May 2026"
    """
    today = date.today()
    record = await get_or_create_record(db, tenant)

    paid_amount = record.amount_paid or Decimal("0.00")
    balance = record.amount_due - paid_amount
    overdue = max((today - record.due_date).days, 0) if balance > 0 else 0

    month_name = record.due_date.strftime("%B %Y")

    return {
        "paid": balance <= 0,
        "amount_due": record.amount_due,
        "amount_paid": paid_amount,
        "balance": balance,
        "due_date": record.due_date,
        "days_overdue": overdue,
        "paid_at": record.paid_at,
        "period": month_name,
        "record_id": str(record.id),
    }


async def mark_paid(
    db: AsyncSession,
    tenant: Tenant,
    amount: Decimal | None = None,
    note: str | None = None,
) -> RentPayment:
    """Mark current month's rent as paid (in full or partial)."""
    record = await get_or_create_record(db, tenant)
    record.amount_paid = amount if amount is not None else record.amount_due
    record.paid_at = datetime.now(timezone.utc)
    record.note = note
    await db.commit()
    await db.refresh(record)
    return record


def format_status_for_tenant(status: dict) -> str:
    """Format rent status as a WhatsApp message for the tenant."""
    period = status["period"]
    due = status["due_date"].strftime("%d %b %Y")
    amount_due = status["amount_due"]

    if status["paid"]:
        paid_on = status["paid_at"].strftime("%d %b") if status["paid_at"] else "recorded"
        return (
            f"✅ *{period} rent — PAID*\n\n"
            f"Amount: €{amount_due:,.2f}\n"
            f"Paid on: {paid_on}"
        )

    balance = status["balance"]
    overdue = status["days_overdue"]
    paid_so_far = status["amount_paid"]

    lines = [f"⚠️ *{period} rent — OUTSTANDING*\n"]
    lines.append(f"Due date: {due}")
    lines.append(f"Amount due: €{amount_due:,.2f}")

    if paid_so_far > 0:
        lines.append(f"Already paid: €{paid_so_far:,.2f}")
        lines.append(f"*Still owed: €{balance:,.2f}*")
    else:
        lines.append(f"*Amount to pay: €{balance:,.2f}*")

    if overdue > 0:
        lines.append(f"\n🔴 *{overdue} day{'s' if overdue != 1 else ''} overdue*")

    return "\n".join(lines)


def format_status_for_landlord(tenant_name: str, unit: str, status: dict) -> str:
    """Format rent status as a landlord-facing summary line."""
    if status["paid"]:
        return f"✅ *{unit}* {tenant_name} — paid €{status['amount_due']:,.2f}"
    overdue = status["days_overdue"]
    tag = f" 🔴 {overdue}d overdue" if overdue else ""
    return (
        f"❌ *{unit}* {tenant_name} — owes €{status['balance']:,.2f}"
        f" (due {status['due_date'].strftime('%d %b')}){tag}"
    )
