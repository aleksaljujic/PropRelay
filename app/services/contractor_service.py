"""
Contractor management service.

All functions operate at the landlord scope — contractors are never shared
across landlords. Specialty filtering is done in Python (not SQL) to keep
queries compatible with both SQLite and PostgreSQL.

Valid specialties: plumbing, electrical, hvac, structural, appliance, general
"""
import structlog
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contractor import Contractor

logger = structlog.get_logger(__name__)

VALID_SPECIALTIES = frozenset(
    {"plumbing", "electrical", "hvac", "structural", "appliance", "general", "it"}
)


async def add_contractor(
    db: AsyncSession,
    landlord_id: UUID,
    name: str,
    phone_number: str,
    specialties: list[str],
    notes: str | None = None,
) -> Contractor:
    """Create and persist a new contractor."""
    invalid = set(specialties) - VALID_SPECIALTIES
    if invalid:
        raise ValueError(f"Invalid specialties: {invalid}. Valid: {sorted(VALID_SPECIALTIES)}")

    contractor = Contractor(
        landlord_id=landlord_id,
        name=name,
        phone_number=phone_number,
        specialties=specialties,
        notes=notes,
        active=True,
    )
    db.add(contractor)
    await db.commit()
    await db.refresh(contractor)
    logger.info("Contractor added", name=name, specialties=specialties)
    return contractor


async def get_contractors_by_landlord(
    db: AsyncSession,
    landlord_id: UUID,
    active_only: bool = True,
) -> list[Contractor]:
    """Return all (active) contractors for a landlord."""
    q = select(Contractor).where(Contractor.landlord_id == landlord_id)
    if active_only:
        q = q.where(Contractor.active.is_(True))
    q = q.order_by(Contractor.name)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_contractors_by_specialty(
    db: AsyncSession,
    landlord_id: UUID,
    specialty: str,
) -> list[Contractor]:
    """
    Return active contractors that list the given specialty.

    Filtering is done in Python to stay SQLite-compatible — contractor lists
    are small (< 50) so this is fine.
    """
    all_contractors = await get_contractors_by_landlord(db, landlord_id, active_only=True)
    matched = [c for c in all_contractors if specialty in (c.specialties or [])]

    # IT / monitor / office equipment — prefer dedicated IT contractors first.
    if specialty in ("appliance", "general"):
        it_specialists = [c for c in all_contractors if "it" in (c.specialties or [])]
        seen: set = set()
        ordered: list[Contractor] = []
        for c in it_specialists + matched:
            if c.id not in seen:
                ordered.append(c)
                seen.add(c.id)
        if ordered:
            return ordered

    return matched


async def deactivate_contractor(
    db: AsyncSession,
    contractor_id: UUID,
) -> Contractor:
    """Mark a contractor as inactive (soft delete)."""
    result = await db.execute(
        select(Contractor).where(Contractor.id == contractor_id)
    )
    contractor = result.scalar_one_or_none()
    if contractor is None:
        raise ValueError(f"Contractor {contractor_id} not found")

    contractor.active = False
    await db.commit()
    await db.refresh(contractor)
    logger.info("Contractor deactivated", contractor_id=str(contractor_id))
    return contractor


async def update_contractor_notes(
    db: AsyncSession,
    contractor_id: UUID,
    notes: str,
) -> Contractor:
    """Update the free-text notes on a contractor."""
    result = await db.execute(
        select(Contractor).where(Contractor.id == contractor_id)
    )
    contractor = result.scalar_one_or_none()
    if contractor is None:
        raise ValueError(f"Contractor {contractor_id} not found")

    contractor.notes = notes
    await db.commit()
    await db.refresh(contractor)
    return contractor
