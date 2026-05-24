"""
Seed the demo SQLite database.

Run after: alembic upgrade head
    python seed_demo.py

Resets any existing data and seeds a clean demo dataset.
"""
import asyncio

from sqlalchemy import delete, text

from app.database import async_session_factory
from app.models.building import Building
from app.models.contractor import Contractor
from app.models.landlord import Landlord
from app.models.tenant import Tenant

# ── Phone numbers — replace with your real test numbers ─────────────────────
LANDLORD_PHONE   = "381603334933"   # Your WhatsApp number (receives landlord notifications)
TENANT_1_PHONE   = "381603334933"   # Number that sends messages as an onboarded tenant
TENANT_2_PHONE   = "381600000002"   # Replace with a second real number to test onboarding
#                                     (must be different from TENANT_1_PHONE)
BUILDING_WA      = "15556402370"    # Meta test phone number


async def seed() -> None:
    async with async_session_factory() as db:
        # ── Wipe existing demo data (order matters — FK constraints) ─────────
        await db.execute(delete(Contractor))
        await db.execute(delete(Tenant))
        await db.execute(delete(Building))
        await db.execute(delete(Landlord))
        await db.commit()

        # ── Landlord ─────────────────────────────────────────────────────────
        landlord = Landlord(
            name="Demo Landlord",
            email="landlord@propflow.demo",
            phone_number=LANDLORD_PHONE,
            whatsapp_verified=True,
            language="de",
        )
        db.add(landlord)
        await db.flush()

        # ── Building ─────────────────────────────────────────────────────────
        building = Building(
            landlord_id=landlord.id,
            name="Musterstraße 12",
            address="Musterstraße 12",
            city="Berlin",
            country="DE",
            whatsapp_number=BUILDING_WA,
        )
        db.add(building)
        await db.flush()

        # ── Tenant 1: already onboarded ──────────────────────────────────────
        tenant_1 = Tenant(
            building_id=building.id,
            landlord_id=landlord.id,
            name="Milan Petrović",
            phone_number=TENANT_1_PHONE,
            unit_number="4B",
            rent_amount=950.00,
            rent_due_day=1,
            language="de",
            active=True,
        )
        db.add(tenant_1)

        # ── Tenant 2: pending onboarding ─────────────────────────────────────
        tenant_2 = Tenant(
            building_id=building.id,
            landlord_id=landlord.id,
            name="Pending",
            phone_number=TENANT_2_PHONE,
            unit_number="2A",
            rent_amount=850.00,
            rent_due_day=1,
            language="de",
            active=True,
        )
        db.add(tenant_2)

        # ── Contractors ───────────────────────────────────────────────────────
        contractor_1 = Contractor(
            landlord_id=landlord.id,
            name="Klaus Wagner",
            phone_number="4916012345678",
            specialties=["plumbing", "general"],
            notes="Available Tue-Fri 8am-5pm. Very reliable.",
            active=True,
        )
        contractor_2 = Contractor(
            landlord_id=landlord.id,
            name="Hans Müller",
            phone_number="4917612345678",
            specialties=["electrical", "appliance"],
            notes="Emergency calls also on weekends. Please call first.",
            active=True,
        )
        contractor_3 = Contractor(
            landlord_id=landlord.id,
            name="Ahmed Yilmaz",
            phone_number="4915112345678",
            specialties=["general", "structural", "hvac"],
            notes="Affordable for smaller jobs. 2 days lead time.",
            active=True,
        )
        db.add_all([contractor_1, contractor_2, contractor_3])
        await db.commit()

    # ── Print summary ─────────────────────────────────────────────────────────
    print("\n✅ Demo data seeded:")
    print(f"  Landlord : {landlord.name} ({landlord.phone_number})")
    print(f"  Building : {building.address}, {building.city}")
    print("  Tenants  :")
    print(f"    - {tenant_1.name:<16} | unit {tenant_1.unit_number} | ✅ onboarded")
    print(f"    - {tenant_2.name:<16} | unit {tenant_2.unit_number} | ⏳ awaiting onboarding")
    print("  Contractors:")
    print(f"    - {contractor_1.name:<14} | {', '.join(contractor_1.specialties)}")
    print(f"    - {contractor_2.name:<14} | {', '.join(contractor_2.specialties)}")
    print(f"    - {contractor_3.name:<14} | {', '.join(contractor_3.specialties)}")

    # ── Initiate onboarding for pending tenant ────────────────────────────────
    print(f"\n⏳ Initiating onboarding for tenant_2 ({tenant_2.phone_number})...")
    try:
        from app.services.onboarding_service import initiate_tenant_onboarding
        await initiate_tenant_onboarding(tenant_2)
        print("   Welcome message sent (or queued). Check WhatsApp on that number.")
    except Exception as exc:
        print(f"   ⚠️  Could not send onboarding message: {exc}")
        print("   (This is expected if the number is a placeholder or not whitelisted in Meta)")

    print()
    print("─" * 55)
    print("Ready for WhatsApp testing:")
    print(f"  Send from {TENANT_1_PHONE} → identified as Milan Petrović")
    print(f"  Send from {TENANT_2_PHONE} → onboarding flow (reply with your name)")
    print("─" * 55)


if __name__ == "__main__":
    asyncio.run(seed())
