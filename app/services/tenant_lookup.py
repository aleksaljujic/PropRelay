"""
Tenant lookup service.

Provides an O(1) query to identify a tenant by their WhatsApp phone number.
Called on every incoming message before routing to the agent.
"""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tenant import Tenant

logger = structlog.get_logger(__name__)


async def get_tenant_by_phone(phone: str, db: AsyncSession) -> Tenant | None:
    """
    Look up an active tenant by their WhatsApp phone number.

    Args:
        phone: E.164 digits-only phone number (no '+'), e.g. "491511234567"
        db:    Async SQLAlchemy session

    Returns:
        Tenant ORM instance with .building and .landlord pre-loaded,
        or None if not found.
    """
    result = await db.execute(
        select(Tenant)
        .where(Tenant.phone_number == phone)
        .where(Tenant.active.is_(True))
        .options(
            selectinload(Tenant.building),
            selectinload(Tenant.landlord),
        )
    )
    tenant = result.scalar_one_or_none()

    if tenant:
        logger.debug(
            "Tenant identified",
            phone=phone,
            name=tenant.name,
            unit=tenant.unit_number,
            building=tenant.building.name,
        )
    else:
        logger.warning("Unknown phone — not in tenant registry", phone=phone)

    return tenant
