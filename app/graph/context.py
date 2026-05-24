"""
Runtime context for graph nodes — avoids serializing DB sessions into Redis.

The orchestrator sets this context before each graph.ainvoke() call.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class NodeContext:
    db: AsyncSession


node_context: ContextVar[NodeContext | None] = ContextVar("node_context", default=None)


def get_node_context() -> NodeContext:
    ctx = node_context.get()
    if ctx is None:
        raise RuntimeError("NodeContext not set — call from orchestrator only")
    return ctx
