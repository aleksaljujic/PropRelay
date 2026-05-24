"""
Deterministic routing functions for conditional edges.

LangGraph calls these after each node — the LLM never controls routing.
"""
from __future__ import annotations

from app.graph.state import GraphState


def route_at_start(state: GraphState) -> str:
    """Skip to landlord approval when tenant already confirmed (recovery path)."""
    if state.get("tenant_confirmed") and state.get("ticket_id"):
        return "prepare_approval"
    return "identify_intent"


def route_by_intent(state: GraphState) -> str:
    if state.get("completed") or state.get("error") == "confirmation_without_context":
        return "__end__"
    intent = state.get("intent")
    if intent == "maintenance":
        # Tenant sent a photo → use Vision AI for diagnosis
        if state.get("media_id"):
            return "diagnose_issue"
        # Text-only request → AI already diagnosed from text in identify_intent
        return "confirm_with_tenant"
    if intent == "complaint":
        return "log_complaint"
    if intent == "rent_query":
        return "rent_status"
    if intent == "admin":
        return "forward_to_landlord"
    if intent == "unknown":
        # If somehow "unknown" slips through, treat as maintenance
        return "confirm_with_tenant"
    # Anything else unrecognised → forward to landlord as admin
    return "forward_to_landlord"


def route_by_severity(state: GraphState) -> str:
    """
    Route after tenant confirms the diagnosis.

    Once the tenant explicitly says YES (= "contact your landlord"),
    we always escalate — even if the AI initially classified the issue
    as minor. The tenant decides whether they want a fix or self-help,
    not the AI. self_help remains routable from other entry points.
    """
    if state.get("tenant_confirmed"):
        return "prepare_approval"
    if state.get("severity") == "minor":
        return "self_help"
    return "prepare_approval"


def route_by_landlord_decision(state: GraphState) -> str:
    if state.get("landlord_approved") is True:
        return "find_contractor"
    if state.get("landlord_approved") is False:
        return "notify_rejection"
    # Still waiting — should not reach here if interrupt works
    return "notify_landlord"


def route_after_dispatch(state: GraphState) -> str:
    if state.get("completed"):
        return "__end__"
    return "dispatch_contractor"
