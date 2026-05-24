"""
Notify landlord with a detailed inspection report + draft contractor message.

This node:
  1. Builds a structured maintenance report from the AI diagnosis
  2. Translates the report into the landlord's language (if needed)
  3. Forwards the tenant's photo to the landlord
  4. Drafts a contractor dispatch message in the contractor's language
  5. Waits for landlord reply:
      - YES → send the draft to contractor (handled in dispatch_contractor)
      - NO → reject
      - Custom text → use that as the contractor message instead
"""
from __future__ import annotations

import uuid

import structlog
from langgraph.types import interrupt
from sqlalchemy import select

from app.config import settings
from app.graph.context import get_node_context
from app.storage.pending_routes import get_thread_contractor_recommendation, register_landlord_pending
from app.graph.state import GraphState
from app.models.landlord import Landlord
from app.models.ticket import ConversationRole
from app.services.ai_service import translate_message
from app.services.contractor_selection import select_contractor_candidates
from app.services.ticket_service import sync_conversation_state
from app.services.whatsapp import forward_image_with_caption, send_text_message
from app.workers.timeout_scheduler import TimeoutKind, schedule_timeout

logger = structlog.get_logger(__name__)

URGENCY_EMOJI = {"emergency": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢"}
SAFETY_EMOJI  = {"high": "⚠️", "medium": "⚠️", "low": "ℹ️", "none": ""}
_APPROVE_WORDS = {"yes", "y", "approve", "approved", "ja", "ok", "da", "👍", "send", "send it", "si", "sì", "evet"}
_REJECT_WORDS  = {"no", "n", "reject", "rejected", "ne", "nein", "👎"}


def _format_minutes(m: int | None) -> str:
    if not m:
        return "—"
    if m < 60:
        return f"{m} min"
    h, rem = divmod(m, 60)
    return f"{h}h {rem}min" if rem else f"{h}h"


def _build_contractor_draft(state: GraphState, contractor_name: str) -> str:
    """Plain-text draft the landlord sees and can edit. English baseline — translated later."""
    summary = state.get("context", {}).get("approval_summary") or {}
    parts = summary.get("parts_needed") or []
    parts_line = ", ".join(parts) if parts else "TBD on inspection"
    return (
        f"Hi {contractor_name},\n\n"
        f"New job at *{state.get('building_name', 'our building')}*, unit *{state.get('unit_number', '?')}*.\n\n"
        f"Issue: {state.get('diagnosis', 'See attached photo')}\n"
        f"Urgency: *{(state.get('urgency') or 'medium').upper()}*\n"
        f"Estimated parts: {parts_line}\n"
        f"Estimated duration: {_format_minutes(summary.get('estimated_duration_minutes'))}\n\n"
        f"Please contact the tenant to schedule.\n"
        f"Reply *CONFIRM* to accept this job."
    )


def _format_landlord_report(state: GraphState, contractor_name: str, contractor_phone: str | None) -> str:
    """Build the structured inspection report (in English, untranslated)."""
    summary  = state.get("context", {}).get("approval_summary") or {}
    urgency  = summary.get("urgency") or state.get("urgency", "medium")
    category = summary.get("category") or state.get("category", "general")
    diagnosis    = state.get("diagnosis") or summary.get("diagnosis", "")
    root_cause   = summary.get("root_cause")
    safety_risk  = summary.get("safety_risk") or "none"
    safety_notes = summary.get("safety_notes")
    estimated    = summary.get("estimated_cost", "TBD")
    duration_min = summary.get("estimated_duration_minutes")
    parts        = summary.get("parts_needed") or []
    tools        = summary.get("tools_needed") or []
    tenant_note  = state.get("context", {}).get("tenant_note", "")

    u_emoji = URGENCY_EMOJI.get(urgency, "🟡")
    s_emoji = SAFETY_EMOJI.get(safety_risk, "")

    parts_section = ""
    if parts:
        parts_section = "\n*Parts needed:*\n" + "\n".join(f"  • {p}" for p in parts)
    tools_section = ""
    if tools:
        tools_section = "\n*Tools required:*\n" + "\n".join(f"  • {t}" for t in tools)

    safety_section = ""
    if safety_risk and safety_risk != "none":
        safety_section = f"\n\n{s_emoji} *Safety risk: {safety_risk.upper()}*"
        if safety_notes:
            safety_section += f"\n_{safety_notes}_"

    root_cause_section = f"\n*Root cause:* {root_cause}" if root_cause else ""
    tenant_note_line   = f"\n*Tenant note:* _{tenant_note}_" if tenant_note else ""

    return (
        f"{u_emoji} *MAINTENANCE INSPECTION REPORT*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Tenant:* {state.get('tenant_name', '')} — Unit *{state.get('unit_number', '?')}*\n"
        f"*Building:* {state.get('building_name', '')}\n"
        f"*Category:* {category.upper()}   |   *Urgency:* {urgency.upper()}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 *Tenant reported:*\n_{state.get('message_text') or summary.get('description') or '—'}_\n\n"
        f"🔍 *Diagnosis*\n{diagnosis}"
        f"{root_cause_section}"
        f"{tenant_note_line}"
        f"{safety_section}\n\n"
        f"💶 *Cost estimate:* {estimated}\n"
        f"⏱ *Estimated work time:* {_format_minutes(duration_min)}"
        f"{parts_section}"
        f"{tools_section}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👷 *Recommended contractor*\n"
        f"{contractor_name}" + (f" ({contractor_phone})" if contractor_phone else "") + "\n\n"
        f"*Reply:*\n"
        f"  • *YES* — dispatch this contractor now\n"
        f"  • *NO* — reject the request\n"
        f"  • Or type your own message to send to the contractor instead"
    )


async def _build_landlord_message(state: GraphState, db) -> tuple[str, str, str | None, str]:
    """Returns (translated_landlord_msg, untranslated_draft, contractor_phone, contractor_language)."""
    category = (state.get("context", {}).get("approval_summary") or {}).get("category") or state.get("category", "general")

    contractor_name = "contractor"
    contractor_phone = None
    contractor_id = None
    contractor_language = "en"
    try:
        candidates = await select_contractor_candidates(
            db, uuid.UUID(state["landlord_id"]), category
        )
        if candidates:
            selected = candidates[0]
            contractor_name = selected.name
            contractor_phone = selected.phone_number
            contractor_id = str(selected.id)
            contractor_language = getattr(selected, "language", None) or "en"
    except Exception as exc:
        logger.warning("Contractor lookup failed", error=str(exc))

    raw_report = _format_landlord_report(state, contractor_name, contractor_phone)
    raw_draft  = _build_contractor_draft(state, contractor_name)

    # Translate report to landlord's language
    landlord = await db.scalar(
        select(Landlord).where(Landlord.id == uuid.UUID(state["landlord_id"]))
    )
    landlord_lang = (landlord.language if landlord else None) or state.get("language", "en")

    translated_report = await translate_message(
        raw_report, landlord_lang, context="property maintenance inspection report"
    )

    return translated_report, raw_draft, contractor_phone, contractor_language, contractor_id, contractor_name


async def notify_landlord(state: GraphState) -> dict:
    ctx = get_node_context()
    db = ctx.db

    # ── Resume path — landlord replied ───────────────────────────────────────
    resume = state.get("resume_value")
    if resume is not None:
        reply = str(resume).strip()
        lower = reply.lower()

        if lower in _REJECT_WORDS:
            logger.info("Landlord rejected", phone=state["phone"])
            return {
                "landlord_approved": False,
                "current_node": "notify_landlord",
                "resume_value": None,
            }

        original_draft = state.get("context", {}).get("contractor_draft", "")
        contractor_language = state.get("context", {}).get("contractor_language", "en")
        base_message = original_draft if lower in _APPROVE_WORDS else reply

        # Translate the final contractor message into their language
        contractor_message = await translate_message(
            base_message, contractor_language, context="WhatsApp message to a contractor"
        )

        logger.info("Landlord approved", custom=(lower not in _APPROVE_WORDS), contractor_lang=contractor_language)
        approved: dict = {
            "landlord_approved": True,
            "contractor_message": contractor_message,
            "current_node": "notify_landlord",
            "resume_value": None,
        }
        rec = await get_thread_contractor_recommendation(state["thread_id"])
        if rec and rec.get("contractor_id"):
            approved["contractor_id"] = rec["contractor_id"]
            approved["contractor_name"] = rec.get("contractor_name")
            approved["contractor_phone"] = rec.get("contractor_phone")
            approved["contractor_candidates"] = [rec["contractor_id"]]
        return approved

    # ── First pass — send to landlord ─────────────────────────────────────────
    landlord_phone = state.get("landlord_phone")
    if not landlord_phone:
        return {"error": "missing_landlord_phone"}

    landlord_msg, draft, contractor_phone, contractor_language, contractor_id, contractor_name = await _build_landlord_message(state, db)

    # 1) Forward the tenant's photo first (if any) so it appears in context
    photo_caption = ""  # the report is sent separately below; keep caption minimal
    forwarded = False
    if state.get("media_id"):
        try:
            forwarded = await forward_image_with_caption(
                landlord_phone,
                state["media_id"],
                caption=photo_caption,
                mime_type=state.get("media_mime") or "image/jpeg",
            )
        except Exception as exc:
            logger.warning("Photo forward to landlord failed", error=str(exc))

    # 2) Send the structured report
    await send_text_message(landlord_phone, landlord_msg)

    await schedule_timeout(
        kind=TimeoutKind.LANDLORD_ESCALATION,
        thread_id=state["thread_id"],
        ticket_id=state.get("ticket_id") or "",
        phone=state["phone"],
        landlord_phone=landlord_phone,
        delay_seconds=settings.timeout_landlord_escalation_seconds,
    )

    await sync_conversation_state(
        db,
        phone=state["phone"],
        role=ConversationRole.tenant,
        state="notify_landlord",
        ticket_id=state.get("ticket_id"),
        context={"awaiting": "landlord_approval"},
    )

    await register_landlord_pending(
        landlord_phone,
        state["thread_id"],
        contractor_id=contractor_id,
        contractor_name=contractor_name,
        contractor_phone=contractor_phone,
    )

    new_context = {
        **state.get("context", {}),
        "contractor_draft": draft,
        "contractor_language": contractor_language,
        "photo_forwarded_to_landlord": forwarded,
    }

    decision = interrupt({"awaiting": "landlord_approval", "ticket_id": state.get("ticket_id")})
    reply = str(decision).strip() if decision else ""
    lower = reply.lower()

    if lower in _REJECT_WORDS:
        return {"landlord_approved": False, "current_node": "notify_landlord", "context": new_context, "resume_value": None}

    base_message = draft if lower in _APPROVE_WORDS else reply
    contractor_message = await translate_message(
        base_message, contractor_language, context="WhatsApp message to a contractor"
    )

    approved_update: dict = {
        "landlord_approved": True,
        "contractor_message": contractor_message,
        "current_node": "notify_landlord",
        "context": new_context,
        "resume_value": None,
    }
    if contractor_id:
        approved_update["contractor_id"] = contractor_id
        approved_update["contractor_name"] = contractor_name
        approved_update["contractor_phone"] = contractor_phone
        approved_update["contractor_candidates"] = [contractor_id]
    return approved_update
