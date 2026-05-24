"""
Admin endpoints — full self-service landlord + tenant registration.

POST /api/v1/admin/register          — register yourself as landlord + building in one shot
POST /api/v1/admin/tenants           — add a tenant (fires WhatsApp onboarding to tenant)
GET  /api/v1/admin/tenants           — list tenants for a landlord
GET  /api/v1/admin/landlords         — list all landlords
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.building import Building
from app.models.contractor import Contractor
from app.models.landlord import Landlord
from app.models.tenant import Tenant
from app.services.onboarding_service import initiate_tenant_onboarding

router = APIRouter()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterLandlordRequest(BaseModel):
    name: str                        # e.g. "Aleksa Ljujic"
    phone: str                       # e.g. "381603334933"  (no +, no spaces)
    email: str                       # e.g. "aleksa@example.com"
    building_name: str               # e.g. "My Apartment Block"
    building_address: str            # e.g. "Kralja Petra 5"
    city: str                        # e.g. "Belgrade"
    whatsapp_number: str             # Meta test number e.g. "15556402370"
    language: str = "en"


class RegisterLandlordOut(BaseModel):
    landlord_id: str
    landlord_name: str
    landlord_phone: str
    building_id: str
    building_name: str


class AddTenantRequest(BaseModel):
    landlord_phone: str              # identifies the landlord
    tenant_phone: str                # new tenant's WhatsApp number
    unit_number: str                 # e.g. "3A"
    language: str = "en"


class TenantOut(BaseModel):
    id: str
    name: str
    phone_number: str
    unit_number: str
    building: str
    active: bool
    onboarding_sent: bool = False


# ---------------------------------------------------------------------------
# POST /admin/register  — one-shot landlord + building setup
# ---------------------------------------------------------------------------

@router.post("/admin/register", response_model=RegisterLandlordOut)
async def register_landlord(body: RegisterLandlordRequest) -> RegisterLandlordOut:
    """
    Register yourself as a landlord and add your first building.
    After this you can POST /admin/tenants to add tenants.
    """
    async with async_session_factory() as db:
        # Prevent duplicate phone/email
        existing = await db.scalar(
            select(Landlord).where(Landlord.phone_number == body.phone)
        )
        if existing:
            # Return existing record instead of erroring — idempotent
            building = await db.scalar(
                select(Building).where(Building.landlord_id == existing.id).limit(1)
            )
            logger.info("Landlord already exists, returning existing record", phone=body.phone)
            return RegisterLandlordOut(
                landlord_id=str(existing.id),
                landlord_name=existing.name,
                landlord_phone=existing.phone_number,
                building_id=str(building.id) if building else "",
                building_name=building.name if building else "(no building)",
            )

        landlord = Landlord(
            name=body.name,
            email=body.email,
            phone_number=body.phone,
            whatsapp_verified=True,
            language=body.language,
        )
        db.add(landlord)
        await db.flush()

        building = Building(
            landlord_id=landlord.id,
            name=body.building_name,
            address=body.building_address,
            city=body.city,
            country="RS",
            whatsapp_number=body.whatsapp_number,
        )
        db.add(building)
        await db.commit()
        await db.refresh(landlord)
        await db.refresh(building)

    logger.info("Landlord registered", name=body.name, phone=body.phone, building=body.building_name)

    return RegisterLandlordOut(
        landlord_id=str(landlord.id),
        landlord_name=landlord.name,
        landlord_phone=landlord.phone_number,
        building_id=str(building.id),
        building_name=building.name,
    )


# ---------------------------------------------------------------------------
# POST /admin/tenants  — landlord adds a tenant → WhatsApp fires immediately
# ---------------------------------------------------------------------------

@router.post("/admin/tenants", response_model=TenantOut)
async def add_tenant(body: AddTenantRequest) -> TenantOut:
    """
    Add a tenant to the landlord's building.
    Immediately sends a WhatsApp onboarding message to the tenant's phone.
    Tenant must reply with their full name to complete registration.
    """
    async with async_session_factory() as db:
        landlord = await db.scalar(
            select(Landlord).where(Landlord.phone_number == body.landlord_phone)
        )
        if not landlord:
            raise HTTPException(
                status_code=404,
                detail=f"Landlord '{body.landlord_phone}' not found. Call POST /api/v1/admin/register first.",
            )

        building = await db.scalar(
            select(Building).where(Building.landlord_id == landlord.id).limit(1)
        )
        if not building:
            raise HTTPException(status_code=404, detail="Landlord has no building registered.")

        existing = await db.scalar(
            select(Tenant).where(Tenant.phone_number == body.tenant_phone)
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Phone {body.tenant_phone} already registered as '{existing.name}'.",
            )

        tenant = Tenant(
            building_id=building.id,
            landlord_id=landlord.id,
            name="Pending",
            phone_number=body.tenant_phone,
            unit_number=body.unit_number,
            language=body.language,
            active=True,
        )
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

    onboarding_sent = False
    try:
        await initiate_tenant_onboarding(tenant)
        onboarding_sent = True
        logger.info("Onboarding WhatsApp sent", phone=body.tenant_phone)
    except Exception as exc:
        logger.warning("WhatsApp send failed", error=str(exc))

    return TenantOut(
        id=str(tenant.id),
        name=tenant.name,
        phone_number=tenant.phone_number,
        unit_number=tenant.unit_number,
        building=building.name,
        active=tenant.active,
        onboarding_sent=onboarding_sent,
    )


# ---------------------------------------------------------------------------
# GET /admin/tenants?landlord_phone=...
# ---------------------------------------------------------------------------

@router.get("/admin/tenants")
async def list_tenants(landlord_phone: str) -> list[TenantOut]:
    async with async_session_factory() as db:
        landlord = await db.scalar(
            select(Landlord).where(Landlord.phone_number == landlord_phone)
        )
        if not landlord:
            raise HTTPException(status_code=404, detail="Landlord not found")

        result = await db.execute(
            select(Tenant)
            .where(Tenant.landlord_id == landlord.id)
            .options(selectinload(Tenant.building))
        )
        tenants = result.scalars().all()

    return [
        TenantOut(
            id=str(t.id),
            name=t.name,
            phone_number=t.phone_number,
            unit_number=t.unit_number,
            building=t.building.name if t.building else "?",
            active=t.active,
        )
        for t in tenants
    ]


# ---------------------------------------------------------------------------
# GET /admin/landlords
# ---------------------------------------------------------------------------

class ContractorIn(BaseModel):
    name: str
    phone_number: str
    specialties: list[str]
    language: str = "en"
    notes: str | None = None


class SeedContractorsRequest(BaseModel):
    landlord_phone: str


DEMO_CONTRACTORS: list[ContractorIn] = [
    ContractorIn(name="Hans Müller",  phone_number="491701234001", specialties=["plumbing", "general"],   language="de", notes="Available Mon–Fri 8–17"),
    ContractorIn(name="Stefan Becker", phone_number="491701234002", specialties=["electrical"],            language="de", notes="24/7 emergencies"),
    ContractorIn(name="Marco Rossi",   phone_number="393331234003", specialties=["hvac", "appliance"],     language="it", notes="Speaks Italian + basic English"),
    ContractorIn(name="Ahmed Yilmaz",  phone_number="905321234004", specialties=["structural", "general"], language="tr", notes="Specializes in masonry"),
    ContractorIn(name="Klaus Wagner",  phone_number="491701234005", specialties=["general", "appliance"],  language="de", notes="Handyman, white goods"),
    ContractorIn(name="Kristina Zivkovic", phone_number="381643492561", specialties=["it", "appliance", "general"], language="en", notes="IIT Service — IT support, monitors, networking, office equipment"),
]


@router.post("/admin/contractors/seed")
async def seed_contractors(body: SeedContractorsRequest) -> dict:
    """Idempotent: seed a roster of demo contractors for a landlord."""
    async with async_session_factory() as db:
        landlord = await db.scalar(
            select(Landlord).where(Landlord.phone_number == body.landlord_phone)
        )
        if not landlord:
            raise HTTPException(status_code=404, detail="Landlord not found")

        created, skipped = [], []
        for c in DEMO_CONTRACTORS:
            existing = await db.scalar(
                select(Contractor)
                .where(Contractor.landlord_id == landlord.id)
                .where(Contractor.phone_number == c.phone_number)
            )
            if existing:
                skipped.append(c.name)
                continue
            db.add(Contractor(
                landlord_id=landlord.id,
                name=c.name,
                phone_number=c.phone_number,
                specialties=c.specialties,
                language=c.language,
                notes=c.notes,
                active=True,
            ))
            created.append(c.name)
        await db.commit()

    logger.info("Contractors seeded", created=created, skipped=skipped)
    return {"created": created, "skipped_existing": skipped}


@router.post("/admin/contractors")
async def add_single_contractor(body: ContractorIn, landlord_phone: str) -> dict:
    async with async_session_factory() as db:
        landlord = await db.scalar(
            select(Landlord).where(Landlord.phone_number == landlord_phone)
        )
        if not landlord:
            raise HTTPException(status_code=404, detail="Landlord not found")
        contractor = Contractor(
            landlord_id=landlord.id,
            name=body.name,
            phone_number=body.phone_number,
            specialties=body.specialties,
            language=body.language,
            notes=body.notes,
            active=True,
        )
        db.add(contractor)
        await db.commit()
        await db.refresh(contractor)
    return {
        "id": str(contractor.id),
        "name": contractor.name,
        "phone_number": contractor.phone_number,
        "specialties": contractor.specialties,
        "language": contractor.language,
    }


@router.get("/admin/landlords")
async def list_landlords() -> list[dict]:
    async with async_session_factory() as db:
        result = await db.execute(select(Landlord))
        landlords = result.scalars().all()
    return [
        {"id": str(l.id), "name": l.name, "phone": l.phone_number, "email": l.email}
        for l in landlords
    ]
