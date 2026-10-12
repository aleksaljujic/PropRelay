# Tenant onboarding and contractors

← [Back to README](../README.md)

## Tenant onboarding flow

Tenants are added by the landlord with `name="Pending"`. The bot then handles the name collection automatically over WhatsApp.

### Step-by-step

```
Landlord                    PropFlow                    Tenant
    │                           │                          │
    │  adds tenant to system    │                          │
    │  (phone + unit, no name)  │                          │
    │──────────────────────────▶│                          │
    │                           │  set Redis state:        │
    │                           │  conv:<phone> =          │
    │                           │  {state: awaiting_name}  │
    │                           │                          │
    │                           │──── welcome message ────▶│
    │                           │  "Hello! Your landlord   │
    │                           │   added you to PropFlow  │
    │                           │   for Musterstraße 12.   │
    │                           │   What is your name?"    │
    │                           │                          │
    │                           │◀──── "Ana Popović" ──────│
    │                           │                          │
    │                           │  DB: tenant.name =       │
    │                           │      "Ana Popović"       │
    │                           │  Redis: clear state      │
    │                           │                          │
    │                           │──── confirmation ───────▶│
    │                           │  "✅ Welcome, Ana!        │
    │                           │   Registered at          │
    │                           │   Musterstraße 12, apt   │
    │                           │   2A. Send a photo or    │
    │                           │   describe any issue."   │
```

### Validation

- Name must contain **at least two words** (first + last name). Single-word replies get a prompt to try again.
- Redis state has a **24-hour TTL** — if the tenant doesn't reply within 24 hours, the state expires and the next message re-triggers onboarding.

### Implementation files

| File | Responsibility |
|------|---------------|
| [app/services/onboarding_service.py](../app/services/onboarding_service.py) | `initiate_tenant_onboarding()`, `handle_onboarding_reply()`, message templates |
| [app/core/redis.py](../app/core/redis.py) | `get_conversation_state()`, `set_conversation_state()`, `clear_conversation_state()` |
| [app/api/v1/webhook.py](../app/api/v1/webhook.py) | Routes to onboarding handlers based on Redis state |

---

## Contractor service

Contractors are managed at landlord scope — each landlord maintains their own contractor list. The service is the lookup layer agents will call to find the right person for a job.

### Functions

| Function | Description |
|----------|-------------|
| `add_contractor(db, landlord_id, name, phone, specialties, notes)` | Create and persist a contractor |
| `get_contractors_by_landlord(db, landlord_id, active_only=True)` | List all (active) contractors |
| `get_contractors_by_specialty(db, landlord_id, specialty)` | Filter by specialty — used by the triage agent |
| `deactivate_contractor(db, contractor_id)` | Soft delete — sets `active=False` |
| `update_contractor_notes(db, contractor_id, notes)` | Update availability / contact notes |

### Valid specialties

`plumbing` · `electrical` · `hvac` · `structural` · `appliance` · `general`

### Example usage

```python
from app.services.contractor_service import get_contractors_by_specialty

# Find all active plumbers for this landlord
plumbers = await get_contractors_by_specialty(db, landlord.id, "plumbing")
# → [Contractor(name="Klaus Wagner", phone="4916012345678", ...)]
```

**Note:** Specialty filtering is done in Python (not SQL) to remain compatible with both SQLite (demo) and PostgreSQL (production). Contractor lists are small so this has no performance impact.

**File:** [app/services/contractor_service.py](../app/services/contractor_service.py)
