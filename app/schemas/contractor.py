from datetime import datetime
from uuid import UUID
from typing import Optional

from pydantic import BaseModel, field_validator

VALID_SPECIALTIES = {"plumbing", "electrical", "hvac", "structural", "appliance", "general"}


class ContractorBase(BaseModel):
    name: str
    phone_number: str
    specialties: list[str] = []
    notes: Optional[str] = None
    active: bool = True

    @field_validator("phone_number")
    @classmethod
    def phone_must_be_e164(cls, v: str) -> str:
        if not v.startswith("+"):
            raise ValueError("phone_number must be in E.164 format (start with +)")
        return v

    @field_validator("specialties")
    @classmethod
    def validate_specialties(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_SPECIALTIES
        if invalid:
            raise ValueError(f"Invalid specialties: {invalid}. Must be one of {VALID_SPECIALTIES}")
        return v


class ContractorCreate(ContractorBase):
    landlord_id: UUID


class ContractorUpdate(BaseModel):
    name: Optional[str] = None
    phone_number: Optional[str] = None
    specialties: Optional[list[str]] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class ContractorResponse(ContractorBase):
    id: UUID
    landlord_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
