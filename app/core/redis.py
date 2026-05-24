"""
Redis async client + conversation-state / ticket-lock helpers.

All keys are namespaced:
  conv:<phone>          — conversation state dict (TTL 24 h)
  lock:ticket:<id>      — optimistic lock owner (TTL 5 min by default)
"""
import json
from typing import Optional

from redis.asyncio import Redis, from_url

from app.config import settings

# Module-level singleton — initialised lazily on first call.
_redis: Optional[Redis] = None


async def get_redis() -> Redis:
    """Return the shared async Redis client, creating it if necessary."""
    global _redis
    if _redis is None:
        _redis = from_url(
            settings.redis_url,
            decode_responses=True,  # all values are strings / JSON
            encoding="utf-8",
        )
    return _redis


async def close_redis() -> None:
    """Gracefully close the Redis connection (call during app shutdown)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# ---------------------------------------------------------------------------
# Conversation state helpers
# ---------------------------------------------------------------------------

_CONV_PREFIX = "conv"
_DEFAULT_CONV_TTL = 86_400  # 24 hours


async def get_conversation_state(phone: str) -> Optional[dict]:
    """
    Fetch conversation state for a phone number.

    Returns:
        Parsed dict or None if not found / expired.
    """
    redis = await get_redis()
    raw = await redis.get(f"{_CONV_PREFIX}:{phone}")
    if raw is None:
        return None
    return json.loads(raw)


async def set_conversation_state(
    phone: str,
    state: dict,
    ttl: int = _DEFAULT_CONV_TTL,
) -> None:
    """
    Persist conversation state for a phone number.

    Args:
        phone: E.164 phone number (the Redis key discriminator)
        state: Arbitrary dict (must be JSON-serialisable)
        ttl:   Seconds until the key expires (default 24 h)
    """
    redis = await get_redis()
    await redis.setex(f"{_CONV_PREFIX}:{phone}", ttl, json.dumps(state))


async def clear_conversation_state(phone: str) -> None:
    """Delete the conversation state for a phone number."""
    redis = await get_redis()
    await redis.delete(f"{_CONV_PREFIX}:{phone}")


# ---------------------------------------------------------------------------
# Ticket optimistic-lock helpers
# ---------------------------------------------------------------------------

_LOCK_PREFIX = "lock:ticket"
_DEFAULT_LOCK_TTL = 300  # 5 minutes


async def set_ticket_lock(
    ticket_id: str,
    locked_by: str,
    ttl: int = _DEFAULT_LOCK_TTL,
) -> bool:
    """
    Acquire an optimistic lock on a ticket (NX = only if not already held).

    Args:
        ticket_id: UUID string of the ticket
        locked_by: "whatsapp" | "dashboard"
        ttl:       Lock expiry in seconds

    Returns:
        True if the lock was acquired, False if already held.
    """
    redis = await get_redis()
    result = await redis.set(
        f"{_LOCK_PREFIX}:{ticket_id}",
        locked_by,
        ex=ttl,
        nx=True,  # set only if key does not exist
    )
    return result is not None


async def release_ticket_lock(ticket_id: str) -> None:
    """Release a ticket lock unconditionally."""
    redis = await get_redis()
    await redis.delete(f"{_LOCK_PREFIX}:{ticket_id}")


async def get_ticket_lock(ticket_id: str) -> Optional[str]:
    """
    Check who holds the lock on a ticket.

    Returns:
        "whatsapp" | "dashboard" | None
    """
    redis = await get_redis()
    return await redis.get(f"{_LOCK_PREFIX}:{ticket_id}")
