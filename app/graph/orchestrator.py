"""
Maintenance orchestration entry point.

Dispatches WhatsApp messages into the LangGraph workflow engine.
Each call runs until the next interrupt() or END — never blocks waiting.
"""
from __future__ import annotations

import structlog
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.builder import get_compiled_graph
from app.graph.context import NodeContext, node_context
from app.graph.state import GraphState
from app.models.landlord import Landlord
from app.models.tenant import Tenant
from app.storage.redis_checkpoint import RedisCheckpointSaver
from app.workers.timeout_scheduler import cancel_timeouts_for_thread

from app.storage.pending_routes import get_contractor_pending_thread, get_landlord_pending_thread

logger = structlog.get_logger(__name__)


class MaintenanceOrchestrator:
    """
    Event-driven workflow engine facade.

    Tenant messages start or resume the maintenance graph.
    Landlord / contractor messages resume human-in-the-loop checkpoints.
    """

    def __init__(self) -> None:
        self._graph = get_compiled_graph()
        self._checkpointer = RedisCheckpointSaver()

    async def dispatch_tenant_message(
        self,
        tenant: Tenant,
        message: dict,
        db: AsyncSession,
    ) -> dict:
        """Process an inbound tenant WhatsApp message."""
        thread_id = tenant.phone_number
        config = {"configurable": {"thread_id": thread_id}}

        state_patch = self._message_to_patch(message)
        initial = self._base_state(tenant) if not await self._has_checkpoint(config) else {}

        merged = {**initial, **state_patch}
        return await self._run_graph(db, config, merged, thread_id)

    async def dispatch_landlord_message(
        self,
        landlord: Landlord,
        text: str,
        db: AsyncSession,
    ) -> dict | None:
        """Resume a paused workflow with landlord YES/NO."""
        thread_id = await get_landlord_pending_thread(landlord.phone_number)
        if not thread_id:
            logger.warning("No pending approval for landlord", phone=landlord.phone_number)
            return None

        config = {"configurable": {"thread_id": thread_id}}
        return await self._run_graph(
            db,
            config,
            {"resume_value": text},
            thread_id,
            resume=True,
        )

    async def dispatch_contractor_message(
        self,
        contractor_phone: str,
        text: str,
        db: AsyncSession,
    ) -> dict | None:
        """Resume contractor confirmation checkpoint."""
        thread_id = await get_contractor_pending_thread(contractor_phone)
        if not thread_id:
            return None

        config = {"configurable": {"thread_id": thread_id}}
        return await self._run_graph(
            db,
            config,
            {"resume_value": text},
            thread_id,
            resume=True,
        )

    async def retry_next_contractor(
        self,
        db: AsyncSession,
        thread_id: str,
        ticket_id: str,
        phone: str,
        current_attempt: int,
    ) -> None:
        """Timeout handler — try next contractor candidate."""
        config = {"configurable": {"thread_id": thread_id}}
        next_attempt = current_attempt + 1

        await self._run_graph(
            db,
            config,
            {
                "contractor_attempt": next_attempt,
                "resume_value": None,
                "contractor_id": None,
                "contractor_phone": None,
            },
            thread_id,
            resume=True,
        )

    async def _run_graph(
        self,
        db: AsyncSession,
        config: dict,
        input_state: dict,
        thread_id: str,
        *,
        resume: bool = False,
    ) -> dict:
        token = node_context.set(NodeContext(db=db))
        try:
            snapshot = await self._graph.aget_state(config)

            if resume and snapshot and snapshot.next:
                logger.info("Resuming graph", thread_id=thread_id, next_nodes=snapshot.next)
                result = await self._graph.ainvoke(
                    Command(resume=input_state.get("resume_value", input_state)),
                    config=config,
                )
            elif snapshot and snapshot.next:
                # Graph interrupted — merge new message data and resume
                logger.info("Resuming interrupted graph with update", thread_id=thread_id)
                if input_state.get("media_id"):
                    result = await self._graph.ainvoke(
                        Command(resume=input_state),
                        config=config,
                    )
                else:
                    result = await self._graph.ainvoke(
                        Command(update=input_state),
                        config=config,
                    )
                    # If still interrupted, try resume with message content
                    snap2 = await self._graph.aget_state(config)
                    if snap2.next:
                        result = await self._graph.ainvoke(
                            Command(resume=input_state),
                            config=config,
                        )
            else:
                logger.info("Starting new graph invocation", thread_id=thread_id)
                full_state: GraphState = {**self._empty_state(), **input_state}  # type: ignore[typeddict-unknown-key]
                result = await self._graph.ainvoke(full_state, config=config)

            if result.get("completed"):
                try:
                    await cancel_timeouts_for_thread(thread_id)
                except Exception as exc:
                    logger.warning("Failed to cancel timeouts", error=str(exc))
                try:
                    await self._checkpointer.adelete_thread(thread_id)
                except Exception as exc:
                    logger.warning("Failed to delete checkpoint", error=str(exc))

            return result
        except Exception as exc:
            logger.exception("Graph execution failed", thread_id=thread_id, error=str(exc))
            raise
        finally:
            node_context.reset(token)

    async def _has_checkpoint(self, config: dict) -> bool:
        snap = await self._graph.aget_state(config)
        return snap.values is not None and bool(snap.values)

    @staticmethod
    def _base_state(tenant: Tenant) -> GraphState:
        landlord = tenant.landlord
        building = tenant.building
        return GraphState(
            thread_id=tenant.phone_number,
            phone=tenant.phone_number,
            tenant_id=str(tenant.id),
            tenant_name=tenant.name,
            unit_number=tenant.unit_number,
            building_id=str(tenant.building_id),
            building_name=building.name if building else "",
            landlord_id=str(tenant.landlord_id),
            landlord_phone=landlord.phone_number if landlord else "",
            language=tenant.language,
            contractor_candidates=[],
            contractor_attempt=0,
            media_urls=[],
            completed=False,
            context={},
        )

    @staticmethod
    def _empty_state() -> GraphState:
        return GraphState(
            contractor_candidates=[],
            contractor_attempt=0,
            media_urls=[],
            completed=False,
            context={},
        )

    @staticmethod
    def _message_to_patch(message: dict) -> dict:
        msg_type = message.get("type", "text")
        patch: dict = {
            "message_id": message.get("id", ""),
            "message_type": msg_type,
            "message_text": "",
        }
        if msg_type == "text":
            patch["message_text"] = message.get("text", {}).get("body", "")
        elif msg_type == "image":
            image = message.get("image", {})
            patch["media_id"] = image.get("id")
            patch["media_mime"] = image.get("mime_type", "image/jpeg")
            patch["message_text"] = image.get("caption", "")
        return patch

    async def get_workflow_status(self, phone: str) -> dict | None:
        """Return current graph state for observability."""
        config = {"configurable": {"thread_id": phone}}
        snap = await self._graph.aget_state(config)
        if not snap.values:
            return None
        return {
            "thread_id": phone,
            "next_nodes": list(snap.next) if snap.next else [],
            "values": dict(snap.values),
            "interrupted": bool(snap.next),
        }


async def lookup_landlord_by_phone(db: AsyncSession, phone: str) -> Landlord | None:
    result = await db.execute(select(Landlord).where(Landlord.phone_number == phone))
    return result.scalar_one_or_none()


orchestrator = MaintenanceOrchestrator()
