from datetime import datetime
from uuid import UUID
from typing import Optional

from pydantic import BaseModel, field_validator


class BuildingBase(BaseModel):
    name: str
    address: str
    city: str
    country: str
    whatsapp_number: str

    @field_validator("whatsapp_number")
    @classmethod
    def phone_must_be_e164(cls, v: str) -> str:
        if not v.startswith("+"):
            raise ValueError("whatsapp_number must be in E.164 format (start with +)")
        return v


class BuildingCreate(BuildingBase):
    landlord_id: UUID


class BuildingUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    whatsapp_number: Optional[str] = None


class BuildingResponse(BuildingBase):
    id: UUID
    landlord_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
