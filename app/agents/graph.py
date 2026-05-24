"""
PropFlow agent graph — LangGraph StateGraph definition.

Flow:
  identify_intent
    ├─ maintenance → request_photo → (waits for image) → diagnose
    │     ├─ self_fix   → END
    │     ├─ emergency  → notify_landlord → END
    │     └─ default    → prepare_approval → notify_landlord → END
    ├─ complaint  → END
    └─ admin/unknown → END
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.state import PropFlowState
from app.agents.nodes import (
    identify_intent,
    request_photo,
    diagnose,
    prepare_approval,
    notify_landlord,
    find_contractor,
)


# ── Routing functions (deterministic — no LLM involvement) ──────────────────

def route_after_intent(state: PropFlowState) -> str:
    intent = state.get("intent")
    if intent == "maintenance":
        return "request_photo"
    # complaint, admin, unknown — acknowledge and close
    return END


def route_after_diagnosis(state: PropFlowState) -> str:
    diagnosis = state.get("diagnosis") or {}
    action = diagnosis.get("recommended_action")
    if action == "self_fix":
        return END
    if action == "emergency":
        return "notify_landlord"
    return "prepare_approval"


# ── Graph construction ───────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(PropFlowState)

    graph.add_node("identify_intent", identify_intent.run)
    graph.add_node("request_photo", request_photo.run)
    graph.add_node("diagnose", diagnose.run)
    graph.add_node("prepare_approval", prepare_approval.run)
    graph.add_node("notify_landlord", notify_landlord.run)
    graph.add_node("find_contractor", find_contractor.run)

    graph.set_entry_point("identify_intent")

    graph.add_conditional_edges(
        "identify_intent",
        route_after_intent,
        {
            "request_photo": "request_photo",
            END: END,
        },
    )

    # request_photo sends the photo ask and halts — next message resumes at diagnose
    graph.add_edge("request_photo", END)

    graph.add_conditional_edges(
        "diagnose",
        route_after_diagnosis,
        {
            END: END,
            "notify_landlord": "notify_landlord",
            "prepare_approval": "prepare_approval",
        },
    )

    graph.add_edge("prepare_approval", "notify_landlord")
    graph.add_edge("notify_landlord", END)    # waits for landlord reply
    graph.add_edge("find_contractor", END)

    return graph.compile()


# Process-level singleton
tenant_graph = build_graph()
