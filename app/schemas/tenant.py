from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from typing import Optional

from pydantic import BaseModel, field_validator


class TenantBase(BaseModel):
    name: str
    phone_number: str
    unit_number: str
    language: str = "de"
    active: bool = True
    rent_amount: Optional[Decimal] = None
    rent_due_day: Optional[int] = None
    lease_start: Optional[date] = None
    lease_end: Optional[date] = None

    @field_validator("phone_number")
    @classmethod
    def phone_must_be_e164(cls, v: str) -> str:
        if not v.startswith("+"):
            raise ValueError("phone_number must be in E.164 format (start with +)")
        return v

    @field_validator("rent_due_day")
    @classmethod
    def rent_due_day_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 28):
            raise ValueError("rent_due_day must be between 1 and 28")
        return v


class TenantCreate(TenantBase):
    building_id: UUID
    landlord_id: UUID


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    phone_number: Optional[str] = None
    unit_number: Optional[str] = None
    language: Optional[str] = None
    active: Optional[bool] = None
    rent_amount: Optional[Decimal] = None
    rent_due_day: Optional[int] = None
    lease_start: Optional[date] = None
    lease_end: Optional[date] = None


class TenantResponse(TenantBase):
    id: UUID
    building_id: UUID
    landlord_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
