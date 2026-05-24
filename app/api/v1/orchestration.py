"""
Orchestration observability endpoints.

GET /api/v1/workflows/{phone} — inspect active graph state (debug).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.graph.orchestrator import orchestrator

router = APIRouter()


@router.get("/workflows/{phone}")
async def get_workflow_status(phone: str) -> dict:
    """
    Return the current LangGraph checkpoint for a tenant phone number.

    Useful for debugging multi-turn workflow state during development.
    """
    status = await orchestrator.get_workflow_status(phone)
    if status is None:
        raise HTTPException(status_code=404, detail="No active workflow for this phone")
    return status
