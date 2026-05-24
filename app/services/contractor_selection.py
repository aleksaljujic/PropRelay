"""
Contractor selection with ordered fallback.

If the primary contractor does not confirm within the timeout window,
the orchestrator tries the next candidate — deterministic, not LLM-driven.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contractor import Contractor
from app.services.contractor_service import get_contractors_by_specialty

logger = structlog.get_logger(__name__)


async def select_contractor_candidates(
    db: AsyncSession,
    landlord_id: uuid.UUID,
    specialty: str,
) -> list[Contractor]:
    """
    Return active contractors for a specialty, ordered by name.

    The orchestration graph walks this list on timeout/rejection.
    """
    contractors = await get_contractors_by_specialty(db, landlord_id, specialty)
    if not contractors:
        contractors = await get_contractors_by_specialty(db, landlord_id, "general")
    logger.info(
        "Contractor candidates selected",
        specialty=specialty,
        count=len(contractors),
    )
    return contractors


def contractor_ids(contractors: list[Contractor]) -> list[str]:
    return [str(c.id) for c in contractors]


def contractor_by_id(contractors: list[Contractor], contractor_id: str) -> Contractor | None:
    for c in contractors:
        if str(c.id) == contractor_id:
            return c
    return None
