"""Redis mappings for human-in-the-loop resume routing."""
from __future__ import annotations

import json

from app.core.redis import get_redis

_LANDLORD_PENDING_PREFIX = "landlord:pending:"
_CONTRACTOR_PENDING_PREFIX = "contractor:pending:"
_THREAD_CONTRACTOR_PREFIX = "thread:contractor:"
_DEFAULT_TTL = 86_400


async def register_landlord_pending(
    landlord_phone: str,
    thread_id: str,
    *,
    contractor_id: str | None = None,
    contractor_name: str | None = None,
    contractor_phone: str | None = None,
    ttl: int = _DEFAULT_TTL,
) -> None:
    redis = await get_redis()
    payload = {
        "thread_id": thread_id,
        "contractor_id": contractor_id,
        "contractor_name": contractor_name,
        "contractor_phone": contractor_phone,
    }
    await redis.setex(
        f"{_LANDLORD_PENDING_PREFIX}{landlord_phone}",
        ttl,
        json.dumps(payload),
    )
    if contractor_id:
        await redis.setex(
            f"{_THREAD_CONTRACTOR_PREFIX}{thread_id}",
            ttl,
            json.dumps(payload),
        )


async def register_contractor_pending(contractor_phone: str, thread_id: str, ttl: int = _DEFAULT_TTL) -> None:
    redis = await get_redis()
    await redis.setex(f"{_CONTRACTOR_PENDING_PREFIX}{contractor_phone}", ttl, thread_id)


async def get_landlord_pending_thread(landlord_phone: str) -> str | None:
    data = await get_landlord_pending(landlord_phone)
    return data.get("thread_id") if data else None


async def get_landlord_pending(landlord_phone: str) -> dict | None:
    redis = await get_redis()
    raw = await redis.get(f"{_LANDLORD_PENDING_PREFIX}{landlord_phone}")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, str):
            return {"thread_id": data}
        return data
    except json.JSONDecodeError:
        return {"thread_id": raw}


async def get_thread_contractor_recommendation(thread_id: str) -> dict | None:
    redis = await get_redis()
    raw = await redis.get(f"{_THREAD_CONTRACTOR_PREFIX}{thread_id}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def get_contractor_pending_thread(contractor_phone: str) -> str | None:
    redis = await get_redis()
    return await redis.get(f"{_CONTRACTOR_PENDING_PREFIX}{contractor_phone}")
