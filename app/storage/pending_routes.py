"""Redis mappings for human-in-the-loop resume routing."""
from __future__ import annotations

from app.core.redis import get_redis

_LANDLORD_PENDING_PREFIX = "landlord:pending:"
_CONTRACTOR_PENDING_PREFIX = "contractor:pending:"
_DEFAULT_TTL = 86_400


async def register_landlord_pending(landlord_phone: str, thread_id: str, ttl: int = _DEFAULT_TTL) -> None:
    redis = await get_redis()
    await redis.setex(f"{_LANDLORD_PENDING_PREFIX}{landlord_phone}", ttl, thread_id)


async def register_contractor_pending(contractor_phone: str, thread_id: str, ttl: int = _DEFAULT_TTL) -> None:
    redis = await get_redis()
    await redis.setex(f"{_CONTRACTOR_PENDING_PREFIX}{contractor_phone}", ttl, thread_id)


async def get_landlord_pending_thread(landlord_phone: str) -> str | None:
    redis = await get_redis()
    return await redis.get(f"{_LANDLORD_PENDING_PREFIX}{landlord_phone}")


async def get_contractor_pending_thread(contractor_phone: str) -> str | None:
    redis = await get_redis()
    return await redis.get(f"{_CONTRACTOR_PENDING_PREFIX}{contractor_phone}")
