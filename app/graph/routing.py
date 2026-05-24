"""
Deterministic routing functions for conditional edges.

LangGraph calls these after each node — the LLM never controls routing.
"""
from __future__ import annotations

from app.graph.state import GraphState


def route_by_intent(state: GraphState) -> str:
    intent = state.get("intent")
    if intent == "maintenance":
        return "confirm_with_tenant"
    if intent == "complaint":
        return "log_complaint"
    if intent == "rent_query":
        return "rent_status"
    if intent == "admin":
        return "forward_to_landlord"
    # "unknown" or anything unrecognised → ask tenant to clarify (don't bother landlord)
    return "clarify_intent"


def route_by_severity(state: GraphState) -> str:
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
