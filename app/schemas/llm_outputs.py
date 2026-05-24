"""
Strict Pydantic schemas for all Claude AI outputs.

LangGraph controls workflow routing — Claude only returns structured data
that nodes use for deterministic decisions.
"""
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TenantIntent(str, Enum):
    maintenance = "maintenance"
    complaint = "complaint"
    rent_query = "rent_query"
    admin = "admin"
    unknown = "unknown"  # LLM fallback — routed same as admin


class IntentClassification(BaseModel):
    """Output of the identify_intent node."""

    intent: TenantIntent
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(max_length=500)
    urgency: Literal["low", "medium", "high", "emergency"] = "medium"

    @field_validator("summary")
    @classmethod
    def summary_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("summary must not be empty")
        return v.strip()


class IssueCategory(str, Enum):
    plumbing = "plumbing"
    electrical = "electrical"
    hvac = "hvac"
    structural = "structural"
    appliance = "appliance"
    general = "general"
    unknown = "unknown"


class DiagnosisResult(BaseModel):
    """Output of the diagnose_issue node (Vision AI)."""

    category: IssueCategory
    severity: Literal["minor", "serious"]
    urgency: Literal["low", "medium", "high", "emergency"]
    diagnosis: str = Field(max_length=2000)
    estimated_cost_min: int | None = Field(default=None, ge=0)
    estimated_cost_max: int | None = Field(default=None, ge=0)
    self_help_steps: list[str] = Field(default_factory=list)
    requires_professional: bool = True

    @field_validator("diagnosis")
    @classmethod
    def diagnosis_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("diagnosis must not be empty")
        return v.strip()


class ApprovalSummary(BaseModel):
    """Structured summary sent to the landlord."""

    ticket_id: str
    tenant_name: str
    unit_number: str
    building_name: str
    category: str
    urgency: str
    diagnosis: str
    estimated_cost: str
    recommended_action: str
