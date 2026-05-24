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
from app.models.ticket import ConversationState, Ticket
from app.services.ticket_service import get_ticket
from app.storage.redis_checkpoint import RedisCheckpointSaver
from app.workers.timeout_scheduler import cancel_timeouts_for_thread

from app.storage.pending_routes import get_contractor_pending_thread, get_landlord_pending_thread

logger = structlog.get_logger(__name__)

_TENANT_CONFIRM = frozenset({"yes", "y", "ok", "correct", "da", "tačno", "tacno", "yep", "sure", "ja", "👍", "✅"})


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
        snapshot = await self._graph.aget_state(config)
        reply_text = state_patch.get("message_text", "").strip()
        is_confirm_reply = (
            not state_patch.get("media_id")
            and reply_text
            and (reply_text.lower() in _TENANT_CONFIRM or len(reply_text) < 4)
        )

        # Graph is paused mid-workflow — resume with the reply, never restart.
        if snapshot and snapshot.next:
            logger.info(
                "Tenant reply resumes interrupted workflow",
                thread_id=thread_id,
                next_nodes=list(snapshot.next),
            )
            if state_patch.get("media_id"):
                return await self._run_graph(
                    db, config, state_patch, thread_id, resume=True,
                )
            return await self._run_graph(
                db,
                config,
                {"resume_value": reply_text},
                thread_id,
                resume=True,
            )

        # Stale DB session without checkpoint — only recover on YES, not new photos.
        awaiting_confirmation = await self._is_awaiting_tenant_confirmation(db, thread_id)
        if awaiting_confirmation:
            await self._checkpointer.adelete_thread(thread_id)
            if is_confirm_reply:
                logger.warning(
                    "Recovering workflow after tenant YES (checkpoint was missing)",
                    thread_id=thread_id,
                )
                return await self._fast_forward_to_landlord(tenant, db, thread_id, config)
            if reply_text and reply_text.lower() not in _TENANT_CONFIRM and len(reply_text) >= 4:
                logger.info("New problem report — clearing stale confirmation session", thread_id=thread_id)
                await self._clear_stale_workflow(db, thread_id)
            elif reply_text:
                return await self._fast_forward_to_landlord(
                    tenant, db, thread_id, config, tenant_note=reply_text,
                )
            else:
                await self._clear_stale_workflow(db, thread_id)

        # Fresh workflow — seed full tenant context + inbound message fields.
        initial = self._base_state(tenant)
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
                resume_payload = input_state.get("resume_value", input_state)
                result = await self._graph.ainvoke(
                    Command(resume=resume_payload),
                    config=config,
                )
            elif snapshot and snapshot.next:
                # Should not happen for tenant path — dispatch_tenant_message handles it.
                logger.warning("Interrupted graph reached _run_graph without resume flag", thread_id=thread_id)
                resume_payload = input_state.get("resume_value") or input_state.get("message_text", "")
                result = await self._graph.ainvoke(
                    Command(resume=resume_payload),
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

    async def _is_awaiting_tenant_confirmation(self, db: AsyncSession, phone: str) -> bool:
        """DB fallback when Redis checkpoint is missing or corrupt."""
        row = await db.scalar(
            select(ConversationState).where(ConversationState.phone_number == phone)
        )
        if not row:
            return False
        ctx = row.context or {}
        return row.state == "confirm_with_tenant" or ctx.get("awaiting") == "tenant_confirmation"

    async def _fast_forward_to_landlord(
        self,
        tenant: Tenant,
        db: AsyncSession,
        thread_id: str,
        config: dict,
        *,
        tenant_note: str | None = None,
    ) -> dict:
        """
        Recover a broken checkpoint: tenant already confirmed, jump to landlord approval.
        """
        row = await db.scalar(
            select(ConversationState).where(ConversationState.phone_number == thread_id)
        )
        ticket = None
        if row and row.current_ticket_id:
            ticket = await get_ticket(db, str(row.current_ticket_id))

        diagnosis = (ticket.ai_diagnosis if ticket else None) or "Issue reported by tenant"
        if tenant_note:
            diagnosis = f"{diagnosis}\nTenant adds: {tenant_note}"

        media_id = None
        media_mime = "image/jpeg"
        if ticket and ticket.media_urls:
            for ref in ticket.media_urls:
                if ref.startswith("meta://"):
                    media_id = ref.replace("meta://", "", 1)
                    break

        recovered: GraphState = {
            **self._base_state(tenant),
            "ticket_id": str(ticket.id) if ticket else None,
            "intent": "maintenance",
            "category": ticket.category.value if ticket and hasattr(ticket.category, "value") else "general",
            "urgency": ticket.urgency.value if ticket and hasattr(ticket.urgency, "value") else "medium",
            "severity": "minor",
            "diagnosis": diagnosis,
            "tenant_confirmed": True,
            "message_text": ticket.description if ticket else "",
            "media_id": media_id,
            "media_mime": media_mime,
            "context": {"tenant_note": tenant_note} if tenant_note else {},
        }
        return await self._run_graph(db, config, recovered, thread_id)

    async def _clear_stale_workflow(self, db: AsyncSession, phone: str) -> None:
        """Drop a leftover confirmation session so a new report can start cleanly."""
        row = await db.scalar(
            select(ConversationState).where(ConversationState.phone_number == phone)
        )
        if row:
            row.state = "completed"
            row.context = {}
            await db.commit()
        await self._checkpointer.adelete_thread(phone)

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
