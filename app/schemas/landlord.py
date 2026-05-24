from datetime import datetime
from uuid import UUID
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


class LandlordBase(BaseModel):
    name: str
    email: str
    phone_number: str
    language: str = "de"

    @field_validator("phone_number")
    @classmethod
    def phone_must_be_e164(cls, v: str) -> str:
        if not v.startswith("+"):
            raise ValueError("phone_number must be in E.164 format (start with +)")
        return v


class LandlordCreate(LandlordBase):
    pass


class LandlordUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    language: Optional[str] = None
    whatsapp_verified: Optional[bool] = None


class LandlordResponse(LandlordBase):
    id: UUID
    whatsapp_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
