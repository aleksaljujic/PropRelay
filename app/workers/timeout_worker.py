"""
Background timeout worker — processes due scheduled events.

Started from FastAPI lifespan; polls Redis every timeout_worker_poll_seconds.
"""
from __future__ import annotations

import asyncio

import structlog

from app.config import settings
from app.database import async_session_factory
from app.graph.orchestrator import orchestrator
from app.services.whatsapp import send_text_message
from app.workers.timeout_scheduler import TimeoutKind, pop_due_jobs

logger = structlog.get_logger(__name__)

_worker_task: asyncio.Task | None = None


async def _handle_timeout_job(job: dict) -> None:
    kind = job.get("kind")
    thread_id = job.get("thread_id", "")
    phone = job.get("phone", "")

    logger.info("Processing timeout", kind=kind, thread_id=thread_id)

    if kind == TimeoutKind.PHOTO_REMINDER.value:
        await send_text_message(
            phone,
            "Reminder: please send a photo of the maintenance issue when you can.",
        )
        return

    if kind == TimeoutKind.LANDLORD_ESCALATION.value:
        landlord_phone = job.get("landlord_phone")
        if landlord_phone:
            await send_text_message(
                landlord_phone,
                "⏰ Escalation: maintenance approval still pending. Please reply YES or NO.",
            )
        return

    if kind == TimeoutKind.CONTRACTOR_CONFIRM.value:
        async with async_session_factory() as db:
            await orchestrator.retry_next_contractor(
                db=db,
                thread_id=thread_id,
                ticket_id=job.get("ticket_id", ""),
                phone=phone,
                current_attempt=job.get("contractor_attempt", 0),
            )
        return


async def _worker_loop() -> None:
    while True:
        try:
            jobs = await pop_due_jobs(limit=20)
            for job in jobs:
                try:
                    await _handle_timeout_job(job)
                except Exception as exc:
                    logger.error("Timeout job failed", error=str(exc), job=job)
        except Exception as exc:
            logger.error("Timeout worker poll failed", error=str(exc))

        await asyncio.sleep(settings.timeout_worker_poll_seconds)


def start_timeout_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())
        logger.info("Timeout worker started")


async def stop_timeout_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    _worker_task = None
    logger.info("Timeout worker stopped")
