"""
LangGraph StateGraph builder — maintenance orchestration workflow.

Graph visualization (Mermaid):

```mermaid
graph TD
    START --> identify_intent
    identify_intent -->|maintenance| request_photo
    identify_intent -->|complaint| log_complaint
    identify_intent -->|admin| forward_to_landlord
    request_photo --> diagnose_issue
    diagnose_issue -->|minor| self_help
    diagnose_issue -->|serious| prepare_approval
    prepare_approval --> notify_landlord
    notify_landlord -->|approved| find_contractor
    notify_landlord -->|rejected| notify_rejection
    find_contractor --> dispatch_contractor
    self_help --> END
    log_complaint --> END
    forward_to_landlord --> END
    notify_rejection --> END
    dispatch_contractor --> END
```
"""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph.routing import (
    route_by_intent,
    route_by_landlord_decision,
    route_by_severity,
)
from app.graph.state import GraphState
from app.nodes.diagnose_issue import diagnose_issue
from app.nodes.dispatch_contractor import dispatch_contractor
from app.nodes.find_contractor import find_contractor
from app.nodes.forward_to_landlord import forward_to_landlord
from app.nodes.identify_intent import identify_intent
from app.nodes.log_complaint import log_complaint
from app.nodes.notify_landlord import notify_landlord
from app.nodes.notify_rejection import notify_rejection
from app.nodes.prepare_approval import prepare_approval
from app.nodes.request_photo import request_photo
from app.nodes.self_help import self_help
from app.storage.redis_checkpoint import RedisCheckpointSaver


def build_maintenance_graph(*, checkpointer: RedisCheckpointSaver | None = None):
    """
    Compile the maintenance orchestration StateGraph.

    Uses interrupt() inside nodes for human-in-the-loop checkpoints.
    Checkpointer persists state in Redis between WhatsApp messages.
    """
    builder = StateGraph(GraphState)

    # ── Nodes (one interaction step each) ─────────────────────────────────
    builder.add_node("identify_intent", identify_intent)
    builder.add_node("request_photo", request_photo)
    builder.add_node("diagnose_issue", diagnose_issue)
    builder.add_node("self_help", self_help)
    builder.add_node("prepare_approval", prepare_approval)
    builder.add_node("notify_landlord", notify_landlord)
    builder.add_node("find_contractor", find_contractor)
    builder.add_node("dispatch_contractor", dispatch_contractor)
    builder.add_node("log_complaint", log_complaint)
    builder.add_node("forward_to_landlord", forward_to_landlord)
    builder.add_node("notify_rejection", notify_rejection)

    # ── Edges ─────────────────────────────────────────────────────────────
    builder.add_edge(START, "identify_intent")

    builder.add_conditional_edges(
        "identify_intent",
        route_by_intent,
        {
            "request_photo": "request_photo",
            "log_complaint": "log_complaint",
            "forward_to_landlord": "forward_to_landlord",
        },
    )

    builder.add_edge("request_photo", "diagnose_issue")

    builder.add_conditional_edges(
        "diagnose_issue",
        route_by_severity,
        {
            "self_help": "self_help",
            "prepare_approval": "prepare_approval",
        },
    )

    builder.add_edge("prepare_approval", "notify_landlord")

    builder.add_conditional_edges(
        "notify_landlord",
        route_by_landlord_decision,
        {
            "find_contractor": "find_contractor",
            "notify_rejection": "notify_rejection",
            "notify_landlord": "notify_landlord",
        },
    )

    builder.add_edge("find_contractor", "dispatch_contractor")
    builder.add_edge("self_help", END)
    builder.add_edge("log_complaint", END)
    builder.add_edge("forward_to_landlord", END)
    builder.add_edge("notify_rejection", END)
    builder.add_edge("dispatch_contractor", END)

    saver = checkpointer or RedisCheckpointSaver()
    return builder.compile(checkpointer=saver)


@lru_cache(maxsize=1)
def get_compiled_graph():
    """Process-wide singleton compiled graph."""
    return build_maintenance_graph()
