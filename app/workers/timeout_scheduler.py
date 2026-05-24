"""
Event-driven timeout scheduler backed by Redis sorted sets.

Timeouts are durable and resumable — the worker picks up due jobs and
injects resume commands into the orchestrator.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum

import structlog

from app.core.redis import get_redis

logger = structlog.get_logger(__name__)

_SCHEDULE_KEY = "timeout:schedule"
_JOB_PREFIX = "timeout:job:"


class TimeoutKind(str, Enum):
    PHOTO_REMINDER = "photo_reminder"
    LANDLORD_ESCALATION = "landlord_escalation"
    CONTRACTOR_CONFIRM = "contractor_confirm"


async def schedule_timeout(
    *,
    kind: TimeoutKind,
    thread_id: str,
    ticket_id: str,
    phone: str,
    delay_seconds: int,
    landlord_phone: str | None = None,
    contractor_phone: str | None = None,
    contractor_attempt: int = 0,
) -> str:
    """
    Schedule a future timeout event.

    Uses Redis ZADD with due timestamp as score for O(log N) polling.
    Returns job_id for cancellation.
    """
    redis = await get_redis()
    job_id = str(uuid.uuid4())
    due_at = datetime.now(timezone.utc).timestamp() + delay_seconds

    payload = {
        "job_id": job_id,
        "kind": kind.value,
        "thread_id": thread_id,
        "ticket_id": ticket_id,
        "phone": phone,
        "landlord_phone": landlord_phone,
        "contractor_phone": contractor_phone,
        "contractor_attempt": contractor_attempt,
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis.setex(f"{_JOB_PREFIX}{job_id}", delay_seconds + 3600, json.dumps(payload))
    await redis.zadd(_SCHEDULE_KEY, {job_id: due_at})

    logger.info(
        "Timeout scheduled",
        kind=kind.value,
        job_id=job_id,
        delay_seconds=delay_seconds,
        thread_id=thread_id,
    )
    return job_id


async def cancel_timeouts_for_thread(thread_id: str) -> int:
    """Cancel all pending timeouts for a workflow thread."""
    redis = await get_redis()
    removed = 0
    now = datetime.now(timezone.utc).timestamp()
    job_ids = await redis.zrangebyscore(_SCHEDULE_KEY, "-inf", now + 86400 * 7)

    for job_id in job_ids:
        raw = await redis.get(f"{_JOB_PREFIX}{job_id}")
        if not raw:
            continue
        payload = json.loads(raw)
        if payload.get("thread_id") == thread_id:
            await redis.zrem(_SCHEDULE_KEY, job_id)
            await redis.delete(f"{_JOB_PREFIX}{job_id}")
            removed += 1
    return removed


async def pop_due_jobs(limit: int = 10) -> list[dict]:
    """Fetch and remove timeout jobs that are due now."""
    redis = await get_redis()
    now = datetime.now(timezone.utc).timestamp()
    job_ids = await redis.zrangebyscore(_SCHEDULE_KEY, "-inf", now, start=0, num=limit)

    jobs: list[dict] = []
    for job_id in job_ids:
        raw = await redis.get(f"{_JOB_PREFIX}{job_id}")
        if raw is None:
            await redis.zrem(_SCHEDULE_KEY, job_id)
            continue
        payload = json.loads(raw)
        await redis.zrem(_SCHEDULE_KEY, job_id)
        await redis.delete(f"{_JOB_PREFIX}{job_id}")
        jobs.append(payload)

    return jobs
