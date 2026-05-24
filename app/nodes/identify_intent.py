"""Classify tenant intent via Claude — routing is deterministic from output."""
from __future__ import annotations

import uuid

import structlog

from app.graph.context import get_node_context
from app.graph.state import GraphState
from app.models.tenant import Tenant
from app.models.ticket import ConversationRole
from app.services.ai_service import classify_intent as _classify_intent
from app.services.ticket_service import create_ticket, sync_conversation_state
from app.services.whatsapp import send_text_message
from app.schemas.llm_outputs import IntentClassification, TenantIntent
from sqlalchemy import select

logger = structlog.get_logger(__name__)

_CONFIRM_ONLY = frozenset({
    "yes", "y", "ok", "okay", "correct", "da", "tačno", "tacno", "yep", "sure",
    "ja", "👍", "✅", "no", "ne", "n",
})


async def identify_intent(state: GraphState) -> dict:
    """
    Single step: classify intent via Claude structured output.

    Creates a ticket immediately for maintenance issues so every workflow
    has a durable audit record from the first message.
    """
    ctx = get_node_context()
    db = ctx.db

    text = state.get("message_text") or ""
    media_id = state.get("media_id")

    # Bare "Yes"/"No" must never spawn a new workflow — those are confirmation replies.
    if not media_id and text.strip().lower() in _CONFIRM_ONLY:
        logger.warning("Confirmation-only message at workflow start — ignoring", phone=state.get("phone"), text=text)
        await send_text_message(
            state["phone"],
            "To report a problem, please describe what's wrong and send a photo if you can.\n"
            "Example: *Monitor is not working* + picture of the issue.",
        )
        return {
            "current_node": "identify_intent",
            "error": "confirmation_without_context",
            "completed": True,
        }

    if not text.strip() and not media_id:
        # Truly empty — sticker, reaction, location, etc.
        return {
            "current_node": "identify_intent",
            "error": "empty_message",
            "awaiting": "description",
        }

    if not text.strip() and media_id:
        # Tenant sent a photo without a caption — treat as maintenance immediately
        logger.info("Image received without caption — routing to vision diagnosis", phone=state.get("phone"))
        tenant = await db.scalar(
            select(Tenant).where(Tenant.id == uuid.UUID(state["tenant_id"]))
        )
        ticket_id = state.get("ticket_id")
        if tenant and not ticket_id:
            ticket = await create_ticket(
                db,
                tenant,
                description="Tenant submitted a photo",
                urgency="medium",
            )
            ticket_id = str(ticket.id)
        await sync_conversation_state(
            db,
            phone=state["phone"],
            role=ConversationRole.tenant,
            state="intent:maintenance",
            ticket_id=ticket_id,
            context={"intent": "maintenance"},
        )
        return {
            "intent": "maintenance",
            "category": "general",
            "severity": "serious",
            "urgency": "medium",
            "diagnosis": "Photo submitted — awaiting vision analysis",
            "ticket_id": ticket_id,
            "current_node": "identify_intent",
        }

    raw = await _classify_intent(text, language=state.get("language", "de"))
    # Safely coerce LLM intent string → enum, fall back to admin for anything unrecognized
    raw_intent = raw.get("intent", "admin")
    try:
        parsed_intent = TenantIntent(raw_intent)
    except ValueError:
        # Unknown string from LLM — treat as maintenance so tenant gets a real response
        logger.warning("Unrecognized intent from LLM, defaulting to maintenance", raw_intent=raw_intent)
        parsed_intent = TenantIntent.maintenance

    # Map raw dict → validated schema for the rest of the graph
    classification = IntentClassification(
        intent=parsed_intent,
        confidence=float(raw.get("confidence") or 0.7),
        summary=raw.get("reasoning") or text[:200],
        urgency=raw.get("urgency") or "medium",
    )
    intent = classification.intent.value
    category = raw.get("category") or "general"
    severity = raw.get("severity") or "serious"
    diagnosis = raw.get("diagnosis") or text[:200]

    logger.info(
        "Intent classified",
        intent=intent,
        confidence=classification.confidence,
        severity=severity,
        category=category,
    )

    update: dict = {
        "intent": intent,
        "urgency": classification.urgency,
        "category": category,
        "severity": severity,
        "diagnosis": diagnosis,
        "current_node": "identify_intent",
        "context": {"intent_summary": classification.summary},
    }

    if intent == TenantIntent.maintenance.value:
        tenant = await db.scalar(
            select(Tenant).where(Tenant.id == uuid.UUID(state["tenant_id"]))
        )
        if tenant and not state.get("ticket_id"):
            ticket = await create_ticket(
                db,
                tenant,
                description=text,
                urgency=classification.urgency,
            )
            update["ticket_id"] = str(ticket.id)

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state=f"intent:{intent}",
        ticket_id=state.get("ticket_id") or update.get("ticket_id"),
        context={"intent": intent},
    )
    return update
