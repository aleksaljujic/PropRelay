# PropFlow

PropFlow is an AI-powered property management platform for EU landlords. Tenants send maintenance requests over WhatsApp, AI agents (built on Claude + LangGraph) triage the issue, collect photos, classify urgency, and draft a repair plan — then ping the landlord for a one-tap approve/reject. Once approved, the right contractor is automatically dispatched and both parties receive status updates throughout the job lifecycle. Landlords can also manage everything through a web dashboard with optimistic locking so WhatsApp and dashboard never conflict.

---

## Table of contents

1. [Tech stack](#tech-stack)
2. [Architecture overview](#architecture-overview)
3. [Request flow](#request-flow)
4. [Bot as middleware](#bot-as-middleware)
5. [Webhook routing](#webhook-routing)
6. [Tenant onboarding flow](#tenant-onboarding-flow)
7. [Contractor service](#contractor-service)
8. [Project structure](#project-structure)
9. [Database models](#database-models)
   - [Landlord](#landlord)
   - [Building](#building)
   - [Tenant](#tenant)
   - [Contractor](#contractor)
   - [Ticket](#ticket)
   - [ConversationState](#conversationstate)
   - [PostgreSQL enums](#postgresql-enums)
   - [Entity-relationship diagram](#entity-relationship-diagram)
10. [API reference](#api-reference)
    - [GET /health](#get-health)
    - [GET /api/v1/webhook](#get-apiv1webhook)
    - [POST /api/v1/webhook](#post-apiv1webhook)
11. [WhatsApp service](#whatsapp-service)
12. [Redis layer](#redis-layer)
13. [Configuration](#configuration)
14. [Demo mode](#demo-mode)
15. [Setup and running](#setup-and-running)
16. [Database migrations](#database-migrations)
17. [Testing](#testing)
18. [Webhook testing with curl](#webhook-testing-with-curl)
19. [Design decisions](#design-decisions)
20. [Roadmap](#roadmap)

---

## Tech stack

| Layer | Technology | Version |
|---|---|---|
| API framework | FastAPI + Uvicorn | 0.111 / 0.30 |
| ORM | SQLAlchemy async | 2.0 |
| Migrations | Alembic | 1.13 |
| Database (prod) | PostgreSQL + pgvector | 15 |
| Database (demo) | SQLite + aiosqlite | — |
| Cache / state | Redis | 7 |
| AI | Anthropic Claude API | — |
| Messaging | Meta WhatsApp Cloud API | v23.0 |
| HTTP client | httpx (async) | 0.27 |
| Validation | Pydantic v2 + pydantic-settings | 2.7 / 2.3 |
| Logging | structlog | 24.1 |
| Packaging | uv | — |
| Container | Docker + docker-compose | — |
| Language | Python | 3.11+ |

---

## Architecture overview

```
                        ┌─────────────────────────────────────────┐
                        │            WhatsApp Cloud API            │
                        │  (Meta Graph API v18.0)                  │
                        └──────────────┬──────────────────────────┘
                                       │ POST /api/v1/webhook
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                        FastAPI App (port 8000)                    │
│                                                                    │
│   Middleware stack:                                                │
│   ① Request-ID injection  →  ② CORS  →  ③ Route dispatch        │
│                                                                    │
│   ┌─────────────────┐    ┌──────────────────────────────────┐    │
│   │  GET /webhook   │    │  POST /webhook                    │    │
│   │  (hub verify)   │    │  ① parse payload                 │    │
│   └─────────────────┘    │  ② return 200 immediately        │    │
│                           │  ③ dispatch BackgroundTask       │    │
│                           └──────────────┬───────────────────┘    │
│                                          │                         │
│        ┌─────────────────────────────────▼──────────────────┐    │
│        │               Background task router                │    │
│        │   (next step: LangGraph agent dispatch)             │    │
│        └──────────────────┬─────────────────────────────────┘    │
│                            │                                       │
│          ┌─────────────────▼───────────────────┐                 │
│          │         WhatsApp Service             │                 │
│          │  send_text_message()                 │                 │
│          │  send_template_message()             │                 │
│          │  download_media()                    │                 │
│          └─────────────────────────────────────┘                 │
└──────────────────────────┬─────────────────────────────────────┬─┘
                            │                                     │
              ┌─────────────▼──────────┐           ┌─────────────▼──────┐
              │    PostgreSQL 15        │           │     Redis 7         │
              │    + pgvector          │           │                     │
              │                        │           │  conv:<phone>       │
              │  landlords             │           │  lock:ticket:<id>   │
              │  buildings             │           │                     │
              │  tenants               │           │  TTL: 24h / 5min    │
              │  contractors           │           └─────────────────────┘
              │  tickets               │
              │  conversation_states   │
              └────────────────────────┘
```

---

## Request flow

The lifecycle of a maintenance request from first WhatsApp message to job completion:

```
Tenant sends WhatsApp message
        │
        ▼
Meta Cloud API  ──POST──▶  POST /api/v1/webhook
                               │
                               ├─ Return 200 immediately (Meta requires < 20 s)
                               │
                               └─ BackgroundTask: _handle_incoming_message()
                                        │
                                        ▼
                              Look up tenant by phone_number
                                        │
                                        ▼
                              Load ConversationState from Redis
                              (fall back to DB if cache miss)
                                        │
                          ┌─────────────▼─────────────────┐
                          │     LangGraph agent router      │  ← next step
                          │  (triage / photo / diagnosis)   │
                          └─────────────┬─────────────────┘
                                        │
                          ┌─────────────▼─────────────────┐
                          │   AI classifies urgency         │
                          │   & category via Claude Vision  │
                          └─────────────┬─────────────────┘
                                        │
                          ┌─────────────▼─────────────────┐
                          │   Landlord approval request     │
                          │   sent via WhatsApp             │
                          │   (or dashboard notification)   │
                          └─────────────┬─────────────────┘
                                        │
                          ┌─────────────▼─────────────────┐
                          │   Contractor dispatched         │
                          │   Ticket status → dispatched    │
                          └─────────────┬─────────────────┘
                                        │
                          ┌─────────────▼─────────────────┐
                          │   Job complete → resolved_at    │
                          │   Ticket status → completed     │
                          └───────────────────────────────┘
```

---

## Bot as middleware

The bot sits **between** tenant and landlord — it owns both WhatsApp conversations and translates between them. Neither party talks to the other directly; every message passes through PropFlow, which adds triage, routing, state, and a full audit trail.

### Full sequence — maintenance request lifecycle

```
Tenant                      PropFlow Bot                    Landlord
  │                               │                              │
  │─── "bathroom pipe leaking" ──▶│                              │
  │                               │  1. look up tenant by phone  │
  │                               │  2. create Ticket (new)      │
  │                               │  3. Claude: classify issue   │
  │                               │     category  → plumbing     │
  │                               │     urgency   → high         │
  │                               │  4. Ticket status → triaged  │
  │                               │                              │
  │◀── "Got it! Can you send ─────│                              │
  │     a photo of the leak?"     │                              │
  │                               │                              │
  │─── [sends image] ────────────▶│                              │
  │                               │  5. download_media()         │
  │                               │  6. Claude Vision: diagnose  │
  │                               │     ai_diagnosis → "Pipe     │
  │                               │     joint failure, seal or   │
  │                               │     replace section"         │
  │                               │  7. Ticket status →          │
  │                               │     awaiting_landlord        │
  │                               │                              │
  │                               │─── "🔧 New ticket – Unit 4B ─▶│
  │                               │     PLUMBING / HIGH          │
  │                               │     'Pipe joint failure'     │
  │                               │     Estimated: €120–180      │
  │                               │     Approve? Reply YES / NO" │
  │                               │                              │
  │                               │◀────────────── "YES" ────────│
  │                               │                              │
  │                               │  8. landlord_approval → True │
  │                               │  9. pick contractor by       │
  │                               │     specialty = plumbing     │
  │                               │ 10. Ticket status →          │
  │                               │     dispatched               │
  │                               │                              │
  │◀── "✅ Approved! A plumber ───│                              │
  │     will contact you soon."   │                              │
  │                               │                              │
  │                               │─── "Job #4821 assigned ─────▶│
  │                               │     to Hans Müller.          │
  │                               │     Scheduled Thursday 10am" │
  │                               │                              │
  │◀── "Hans Müller (plumber) ────│                              │
  │     is coming Thursday at     │                              │
  │     10am. Please be home."    │                              │
  │                               │                              │
  │─── "Done, thanks!" ──────────▶│                              │
  │                               │ 11. Ticket status →          │
  │                               │     completed                │
  │                               │ 12. resolved_at = now()      │
  │                               │                              │
```

---

### Three operating modes

**Mode 1 — Full autonomous** (default PropFlow mode)

The bot handles the full conversation. Landlord only sees an approve/reject ping — one tap, no back-and-forth.

```
Tenant ──▶ Bot ──▶ [AI triage + diagnosis] ──▶ Landlord (YES / NO only)
                                                      │
                              Contractor ◀────────────┘  (bot dispatches)
```

**Mode 2 — Transparent relay**

The bot forwards raw messages with added context (tenant name, unit, ticket history). Landlord types replies freely; bot delivers them.

```
Tenant ──▶ Bot ──▶ Landlord
           Bot       │
Tenant ◀───────── reply
```
Useful when the landlord prefers to handle the conversation personally but still wants the message routed and logged.

**Mode 3 — Hybrid**

Routine issues (low/medium urgency, known category) are resolved autonomously. Complex, expensive, or emergency issues escalate to the landlord loop.

```
Tenant ──▶ Bot ──▶ [AI: is this routine?]
                        │              │
                   yes (auto)      no (escalate)
                        │              │
                   Bot resolves    Landlord loop
                   Ticket →           │
                   completed      Mode 1 flow
```

---

### How the bot tells tenant from landlord

Meta delivers every inbound message to the same `POST /webhook` endpoint. The bot differentiates using the `from` phone number looked up against the database:

```python
# Background task router (next step — agents/router.py)
role = await db.scalar(
    select(ConversationState.role)
    .where(ConversationState.phone_number == sender_phone)
)

if role == ConversationRole.tenant:
    await tenant_graph.run(sender_phone, message)
elif role == ConversationRole.landlord:
    await landlord_graph.run(sender_phone, message)
elif role == ConversationRole.contractor:
    await contractor_graph.run(sender_phone, message)
```

`ConversationState.role` is set when a phone number is first registered in the system. After that, every message is automatically routed to the correct conversation graph with no manual routing logic.

---

### What PropFlow already has that makes this work

| Component | Role in the middleware |
|---|---|
| `Tenant.phone_number` (indexed) | O(1) lookup: who is writing? |
| `ConversationState.role` | tenant / landlord / contractor routing gate |
| `ConversationState.state` | which graph node are they in right now? |
| `ConversationState.context` (JSONB) | carry data between turns without re-querying |
| `Ticket.landlord_approval` | `None` = pending · `True` = approved · `False` = rejected |
| `Ticket.locked_by` | prevents WhatsApp and dashboard editing the same ticket at once |
| `send_text_message()` | push replies to either party |
| `BackgroundTask` pattern | landlord reply triggers tenant notification without blocking |
| Redis conversation TTL (24 h) | auto-expire idle conversations without manual cleanup |

---

### Plug-in point in the current code

The stub comment in [app/api/v1/webhook.py](app/api/v1/webhook.py) marks exactly where the agent router connects:

```python
# TODO (next step): route to LangGraph agent
# await agent_router.dispatch(tenant, message)
```

Everything above that line — webhook parsing, phone lookup, Redis state, DB writes, WhatsApp sends — is already working. The agent graphs slot in at that single point.

---

## Webhook routing

Every incoming WhatsApp message passes through a single routing function `_handle_incoming_message`. It follows this decision tree:

```
Incoming message (sender_phone, text_body)
          │
          ▼
  get_tenant_by_phone(sender_phone)
          │
     ┌────┴──────────────────────────┐
     │ NOT found                     │ found
     ▼                               ▼
"Your number is not          check Redis conv state
 registered. Contact          conv:<phone>
 your landlord."                    │
                      ┌─────────────┼───────────────────┐
                      │ state =     │ name =             │ registered
                      │ awaiting_   │ "Pending"          │ tenant
                      │ name        │                    │
                      ▼             ▼                    ▼
               handle_onboarding_  initiate_        "Got it, {name}!
               reply()             onboarding()     Your message has
               → save name         → re-send        been received."
               → confirm           welcome msg
               → clear Redis                        (→ agent next)
```

**Key rule:** The bot only knows about tenants the landlord has explicitly added. Unknown numbers always get the "not registered" message — there is no self-registration.

---

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
| [app/services/onboarding_service.py](app/services/onboarding_service.py) | `initiate_tenant_onboarding()`, `handle_onboarding_reply()`, message templates |
| [app/core/redis.py](app/core/redis.py) | `get_conversation_state()`, `set_conversation_state()`, `clear_conversation_state()` |
| [app/api/v1/webhook.py](app/api/v1/webhook.py) | Routes to onboarding handlers based on Redis state |

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

**File:** [app/services/contractor_service.py](app/services/contractor_service.py)

---

```
propflow/
│
├── Dockerfile                      # Multi-stage build for production image
├── docker-compose.yml              # Production: app + postgres + redis
├── docker-compose.dev.yml          # Dev override: hot-reload + volume mounts
│
├── pyproject.toml                  # Project metadata + all dependencies (uv)
├── alembic.ini                     # Alembic config (URL overridden from .env)
├── .env.example                    # Template — copy to .env and fill in secrets
├── .gitignore
├── README.md
│
├── alembic/
│   ├── env.py                      # Async Alembic environment (asyncpg-compatible)
│   └── versions/
│       └── 0001_initial_schema.py  # Migration: all 6 tables + 5 PG enums + extensions
│
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app factory, lifespan, middleware, /health
│   ├── config.py                   # Pydantic-settings — reads .env, cached singleton
│   ├── database.py                 # Async SQLAlchemy engine + get_db() dependency
│   │
│   ├── models/                     # SQLAlchemy 2.0 ORM models (Mapped[] syntax)
│   │   ├── __init__.py             # Re-exports all models so Base.metadata is complete
│   │   ├── base.py                 # DeclarativeBase + TimestampMixin
│   │   ├── landlord.py             # Landlord — property owner
│   │   ├── building.py             # Building — a property with units
│   │   ├── tenant.py               # Tenant — identified by phone_number
│   │   ├── contractor.py           # Contractor — maintenance worker
│   │   └── ticket.py               # Ticket, ConversationState, all 5 enums
│   │
│   ├── schemas/                    # Pydantic v2 request / response models
│   │   ├── __init__.py
│   │   ├── landlord.py
│   │   ├── building.py
│   │   ├── tenant.py
│   │   ├── contractor.py
│   │   └── ticket.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py               # Top-level APIRouter: mounts all v1 sub-routers
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── webhook.py          # GET + POST /api/v1/webhook handlers
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── whatsapp.py             # Meta Cloud API: send text/template, download media
│   │   ├── tenant_lookup.py        # O(1) phone → Tenant query (called on every message)
│   │   ├── onboarding_service.py   # Tenant onboarding flow + message templates
│   │   └── contractor_service.py   # Contractor CRUD + specialty-based lookup
│   │
│   └── core/
│       ├── __init__.py
│       └── redis.py                # Async Redis client + conversation/lock helpers
│
├── seed_demo.py                    # Seeds SQLite with landlord + building + tenants + contractors
│
└── tests/
    ├── __init__.py
    ├── conftest.py                 # Pytest fixtures — mocks DB + Redis for unit tests
    ├── test_webhook.py             # 8 tests covering verification + message types
    └── test_onboarding.py          # 5 integration tests for the onboarding state machine
```

---

## Database models

All models use **SQLAlchemy 2.0** with the `Mapped[T]` / `mapped_column()` annotation style. All primary keys are **UUIDs** generated by `uuid.uuid4()`. Tables that represent owned resources include `created_at` and `updated_at` timestamps via `TimestampMixin`.

### Landlord

**File:** [app/models/landlord.py](app/models/landlord.py)  
**Table:** `landlords`

The top-level system user. Owns one or more buildings, a roster of contractors, and has all tenants indirectly assigned under them.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK | Auto-generated v4 UUID |
| `name` | `VARCHAR(255)` | NOT NULL | Full display name |
| `email` | `VARCHAR(255)` | NOT NULL, UNIQUE | Login identifier |
| `phone_number` | `VARCHAR(50)` | NOT NULL, UNIQUE | E.164 format, e.g. `+49151...` |
| `whatsapp_verified` | `BOOLEAN` | NOT NULL, default `false` | True once the landlord has confirmed their WhatsApp number |
| `language` | `VARCHAR(10)` | NOT NULL, default `"de"` | BCP-47 language code for AI replies |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, server default | Set by DB on insert |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, server default | Updated by ORM on save |

**Relationships:**
- `buildings` → `list[Building]` (cascade delete-orphan)
- `tenants` → `list[Tenant]`
- `contractors` → `list[Contractor]` (cascade delete-orphan)

---

### Building

**File:** [app/models/building.py](app/models/building.py)  
**Table:** `buildings`

A physical property. Each building gets its **own dedicated WhatsApp number** — tenants message that number, so the system always knows which building a request belongs to before even looking up the tenant.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK | Auto-generated v4 UUID |
| `landlord_id` | `UUID` | FK → `landlords.id`, CASCADE | Owner |
| `name` | `VARCHAR(255)` | NOT NULL | Display name, e.g. `"Musterstraße 12"` |
| `address` | `VARCHAR(500)` | NOT NULL | Street address |
| `city` | `VARCHAR(100)` | NOT NULL | City |
| `country` | `VARCHAR(100)` | NOT NULL | Country code, e.g. `"DE"` |
| `whatsapp_number` | `VARCHAR(50)` | NOT NULL, UNIQUE | Dedicated E.164 number for this building |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, server default | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, server default | |

**Relationships:**
- `landlord` → `Landlord`
- `tenants` → `list[Tenant]` (cascade delete-orphan)
- `tickets` → `list[Ticket]`

---

### Tenant

**File:** [app/models/tenant.py](app/models/tenant.py)  
**Table:** `tenants`

A person living in a unit. The **primary identifier is `phone_number`** — every incoming WhatsApp message is matched against this column to find who is writing. The column has a unique constraint and a B-tree index.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK | Auto-generated v4 UUID |
| `building_id` | `UUID` | FK → `buildings.id`, CASCADE | Which building they live in |
| `landlord_id` | `UUID` | FK → `landlords.id` | Denormalised for fast landlord lookups |
| `name` | `VARCHAR(255)` | NOT NULL | Display name |
| `phone_number` | `VARCHAR(50)` | NOT NULL, UNIQUE, INDEX | E.164 — used as WhatsApp lookup key |
| `unit_number` | `VARCHAR(20)` | NOT NULL | Apartment identifier, e.g. `"4B"` |
| `rent_amount` | `NUMERIC(10,2)` | nullable | Monthly rent in local currency |
| `rent_due_day` | `INTEGER` | nullable | Day of month rent is due (1–28) |
| `lease_start` | `DATE` | nullable | Lease start date |
| `lease_end` | `DATE` | nullable | Lease end date |
| `language` | `VARCHAR(10)` | NOT NULL, default `"de"` | BCP-47 for AI response language |
| `active` | `BOOLEAN` | NOT NULL, default `true` | Soft-delete / inactive tenants |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, server default | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, server default | |

**Relationships:**
- `building` → `Building`
- `landlord` → `Landlord`
- `tickets` → `list[Ticket]`

---

### Contractor

**File:** [app/models/contractor.py](app/models/contractor.py)  
**Table:** `contractors`

A maintenance worker in the landlord's trusted network. The `specialties` column is a **PostgreSQL native array** so the agent can filter contractors by capability (e.g. `WHERE 'plumbing' = ANY(specialties)`).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK | Auto-generated v4 UUID |
| `landlord_id` | `UUID` | FK → `landlords.id`, CASCADE | Owner |
| `name` | `VARCHAR(255)` | NOT NULL | Display name |
| `phone_number` | `VARCHAR(50)` | NOT NULL | E.164 — for WhatsApp dispatch |
| `specialties` | `TEXT[]` | nullable | Array: `["plumbing", "electrical", "hvac", "general"]` |
| `notes` | `TEXT` | nullable | Free-form notes, e.g. `"only available Tue–Thu"` |
| `active` | `BOOLEAN` | NOT NULL, default `true` | Deactivate without deleting |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, server default | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, server default | |

**Valid specialty values:** `plumbing`, `electrical`, `hvac`, `structural`, `appliance`, `general`

**Relationships:**
- `landlord` → `Landlord`
- `tickets` → `list[Ticket]`

---

### Ticket

**File:** [app/models/ticket.py](app/models/ticket.py)  
**Table:** `tickets`

The central entity — every maintenance request becomes a ticket. Tracks the full lifecycle from first message through AI diagnosis, landlord approval, contractor dispatch, scheduling and resolution.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK | Auto-generated v4 UUID |
| `building_id` | `UUID` | FK → `buildings.id`, INDEX | Which building |
| `tenant_id` | `UUID` | FK → `tenants.id`, INDEX | Who reported it |
| `contractor_id` | `UUID` | FK → `contractors.id`, nullable | Assigned once approved |
| `status` | `ticketstatus` | NOT NULL, default `new` | Lifecycle state machine — see enum below |
| `category` | `ticketcategory` | NOT NULL, default `unknown` | Problem type — see enum below |
| `urgency` | `ticketurgency` | NOT NULL, default `medium` | Priority level — see enum below |
| `description` | `TEXT` | NOT NULL | Tenant's original message verbatim |
| `ai_diagnosis` | `TEXT` | nullable | Claude Vision analysis result |
| `media_urls` | `TEXT[]` | nullable | URLs of uploaded images/videos |
| `landlord_approval` | `BOOLEAN` | nullable | `NULL` = pending, `true` = approved, `false` = rejected |
| `locked_by` | `lockedby` | nullable | Optimistic lock holder: `"whatsapp"` or `"dashboard"` |
| `locked_at` | `TIMESTAMPTZ` | nullable | When the lock was acquired |
| `scheduled_at` | `TIMESTAMPTZ` | nullable | Confirmed appointment with contractor |
| `resolved_at` | `TIMESTAMPTZ` | nullable | When the job was marked complete |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, server default | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, server default | |

**Indexes:** `status`, `tenant_id`, `building_id`

**Relationships:**
- `building` → `Building`
- `tenant` → `Tenant`
- `contractor` → `Contractor` (optional)

**Ticket status state machine:**

```
new ──▶ triaged ──▶ awaiting_landlord ──▶ approved ──▶ dispatched ──▶ scheduled ──▶ completed
                                      └──▶ rejected
any state ──▶ self_resolved   (tenant cancels before landlord approves)
```

---

### ConversationState

**File:** [app/models/ticket.py](app/models/ticket.py)  
**Table:** `conversation_states`

Tracks the LangGraph node each phone number is currently in. The **primary store is Redis** (TTL 24 h); this table is a persistence backup for crash recovery and audit.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK | Auto-generated v4 UUID |
| `phone_number` | `VARCHAR(50)` | NOT NULL, UNIQUE, INDEX | E.164 — one row per active conversation |
| `role` | `conversationrole` | NOT NULL | `tenant`, `landlord`, or `contractor` |
| `current_ticket_id` | `UUID` | FK → `tickets.id`, nullable | The ticket being worked on right now |
| `state` | `VARCHAR(100)` | NOT NULL | LangGraph node name, e.g. `"awaiting_image"`, `"awaiting_approval"` |
| `context` | `JSONB` | nullable | Arbitrary structured state the agent needs between turns |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, server default | Last updated — used for stale-conversation detection |

---

### PostgreSQL enums

All enums are **native PostgreSQL `ENUM` types** (not `VARCHAR` with a check constraint). This makes them first-class DB types with typo safety and indexing.

#### `ticketstatus`
Controls the ticket lifecycle:

| Value | Meaning |
|---|---|
| `new` | Just created — no AI processing yet |
| `triaged` | AI has classified category and urgency |
| `awaiting_landlord` | Waiting for landlord approve/reject |
| `approved` | Landlord approved, ready to dispatch |
| `dispatched` | Contractor has been contacted |
| `scheduled` | Contractor appointment confirmed |
| `completed` | Job done, tenant confirmed |
| `rejected` | Landlord rejected the request |
| `self_resolved` | Tenant cancelled (fixed themselves, false alarm, etc.) |

#### `ticketcategory`
What type of problem it is:

| Value | Examples |
|---|---|
| `plumbing` | Leaking pipe, blocked drain, no hot water |
| `electrical` | Broken outlet, flickering lights, tripped breaker |
| `hvac` | Heating not working, A/C failure |
| `structural` | Cracked wall, roof leak, broken door |
| `appliance` | Broken oven, washing machine failure |
| `general` | Doesn't fit other categories |
| `complaint` | Noise, neighbour issues |
| `admin` | Lease question, document request |
| `unknown` | Default — AI hasn't classified yet |

#### `ticketurgency`

| Value | Response expectation |
|---|---|
| `low` | Within a week |
| `medium` | Within a few days (default) |
| `high` | Same day |
| `emergency` | Immediate — e.g. gas leak, flooding |

#### `lockedby`
Optimistic lock owner for concurrent WhatsApp + dashboard edits:

| Value | Meaning |
|---|---|
| `whatsapp` | The agent conversation holds the lock |
| `dashboard` | A landlord browser session holds the lock |

#### `conversationrole`
Who is on the other end of a phone number:

| Value | Meaning |
|---|---|
| `tenant` | Reporting a problem |
| `landlord` | Approving / reviewing |
| `contractor` | Confirming availability / completing jobs |

---

### Entity-relationship diagram

```
landlords
  │ id (PK)
  │ email (UNIQUE)
  │ phone_number (UNIQUE)
  │
  ├──< buildings (landlord_id FK, CASCADE)
  │      │ id (PK)
  │      │ whatsapp_number (UNIQUE)
  │      │
  │      └──< tenants (building_id FK, CASCADE)
  │             │ id (PK)
  │             │ phone_number (UNIQUE, INDEX)  ← WhatsApp lookup key
  │             │ landlord_id FK
  │             │
  │             └──< tickets (tenant_id FK)
  │                    │ id (PK)
  │                    │ building_id FK
  │                    │ contractor_id FK (nullable)
  │                    │ status / category / urgency  ← native PG enums
  │                    │ landlord_approval (NULL | true | false)
  │                    │ locked_by / locked_at  ← optimistic lock
  │                    │
  │                    └──? conversation_states (current_ticket_id FK)
  │                           phone_number (UNIQUE, INDEX)
  │                           state / context (JSONB)
  │
  └──< contractors (landlord_id FK, CASCADE)
         id (PK)
         specialties TEXT[]  ← native PG array
```

---

## API reference

All endpoints are prefixed under the FastAPI app mounted at port **8000**. Interactive docs (Swagger UI) available at `/docs` when `DEBUG=true`.

---

### GET /health

Liveness + readiness probe. Checks both PostgreSQL and Redis connectivity.

**Response `200 OK`:**
```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "version": "0.1.0"
}
```

If either backend is unreachable, `status` becomes `"degraded"` and the affected field becomes `"error"`. The HTTP status code is always `200` so load balancers can inspect the body.

Every request also returns the header **`X-Request-ID`** — a UUID injected by the request-ID middleware for log correlation.

---

### GET /api/v1/webhook

**Purpose:** Meta hub verification — called once by Meta when you register the webhook URL in the developer console.

**Query parameters:**

| Parameter | Alias | Description |
|---|---|---|
| `hub.mode` | required | Must equal `"subscribe"` |
| `hub.verify_token` | required | Must match `META_WEBHOOK_VERIFY_TOKEN` in `.env` |
| `hub.challenge` | required | Random string Meta expects echoed back |

**Success `200`:** Returns `hub.challenge` as plain text.  
**Failure `403`:** Wrong mode or wrong verify token.

**Implementation note:** FastAPI's `Query(alias=...)` maps the dot-notation parameter names (`hub.mode`) to Python-safe identifiers (`hub_mode`).

---

### POST /api/v1/webhook

**Purpose:** Receives all incoming WhatsApp messages and status updates from Meta.

**Design contract:** Returns `200 OK` immediately — Meta requires a response within 20 seconds or will retry. All heavy processing (AI triage, DB writes, sending replies) runs in a **`BackgroundTask`** after the response is sent.

**Request body:** Standard Meta webhook payload (JSON). The endpoint handles:

| Message type | What's extracted |
|---|---|
| `text` | `from` (phone), `text.body` |
| `image` | `from`, `image.id` (media_id), `image.caption` |
| `audio` | `from`, `audio.id` |
| `video` | `from`, `video.id` |
| `document` | `from`, `document.id`, `document.filename` |
| Status updates | `id`, `status` (`delivered`/`read`), `recipient_id` |

Non-WhatsApp payloads (`object != "whatsapp_business_account"`) return `{"status": "ignored"}`.

**Success `200`:**
```json
{"status": "ok"}
```

**Background task handler (`_handle_incoming_message`):**  
Parses the message, logs with structlog (bound with `phone`, `message_id`, `type`), and prints to stdout. The stub comment marks where LangGraph agent dispatch will be wired in the next development step.

---

## WhatsApp service

**File:** [app/services/whatsapp.py](app/services/whatsapp.py)

Three async functions using `httpx.AsyncClient`. All calls target `https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages`.

### `send_text_message(phone, text)`

Sends a plain-text message. Max body length is 4096 characters (Meta limit).

```python
await send_text_message("+49151234567", "Ihr Ticket wurde erstellt.")
```

### `send_template_message(phone, template, params, language_code="de")`

Sends a pre-approved Meta message template with parameter injection. Required for sending the first message to a user who hasn't written to you in the last 24 hours.

```python
await send_template_message(
    phone="+49151234567",
    template="maintenance_update",
    params=["Ticket #1234", "genehmigt"],
)
```

### `download_media(media_id)`

Two-step download: first resolves the temporary CDN URL from the Meta media endpoint, then downloads the raw bytes. Use this to store images tenants send.

```python
image_bytes = await download_media("media_id_from_webhook_payload")
```

All methods raise `httpx.HTTPStatusError` on non-2xx responses.

---

## Redis layer

**File:** [app/core/redis.py](app/core/redis.py)

A lazily-initialised async Redis client (singleton) plus six helper functions. All keys use string namespacing to avoid collisions.

### Key schema

| Key pattern | TTL | Value | Purpose |
|---|---|---|---|
| `conv:<phone>` | 24 h (86 400 s) | JSON string | Conversation state dict |
| `lock:ticket:<uuid>` | 5 min (300 s) | `"whatsapp"` or `"dashboard"` | Optimistic lock owner |

### `get_redis() → Redis`

Returns the shared async client. Creates it on first call using `REDIS_URL` from settings. `decode_responses=True` so all values are plain strings / JSON — no bytes decoding needed.

### `close_redis()`

Called by the FastAPI lifespan on shutdown. Sends `QUIT` and cleans up the connection.

### Conversation state helpers

```python
# Store state after each agent turn
await set_conversation_state("+49151234567", {
    "state": "awaiting_image",
    "ticket_id": "uuid...",
    "retry_count": 1,
})

# Retrieve on next incoming message
state = await get_conversation_state("+49151234567")
# → {"state": "awaiting_image", "ticket_id": "...", ...} or None

# Clear when conversation finishes
await clear_conversation_state("+49151234567")
```

### Ticket lock helpers

Prevents a landlord's dashboard session and an active WhatsApp conversation from simultaneously modifying the same ticket.

```python
# Try to acquire lock — returns False immediately if already held
acquired = await set_ticket_lock("ticket-uuid", "whatsapp", ttl=300)

# Check who holds the lock
owner = await get_ticket_lock("ticket-uuid")  # "whatsapp" | "dashboard" | None

# Release when done
await release_ticket_lock("ticket-uuid")
```

The lock uses Redis `SET NX` (set-if-not-exists) so it is atomic with no race conditions.

---

## Configuration

**File:** [app/config.py](app/config.py)

All configuration is in a single `Settings` class backed by **pydantic-settings**. Values are read from environment variables (case-insensitive) with `.env` file fallback. The instance is cached with `@lru_cache` so `.env` is only parsed once per process.

```python
from app.config import settings
print(settings.database_url)
```

### Full variable reference

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `APP_NAME` | str | `propflow` | — | Application name |
| `APP_ENV` | str | `development` | — | `development` or `production` |
| `DEBUG` | bool | `true` | — | Enables SQL echo, Swagger UI, console log renderer |
| `SECRET_KEY` | str | `change-me-in-production` | **prod** | Used for signing tokens / session cookies |
| `DATABASE_URL` | str | `postgresql+asyncpg://propflow:propflow@localhost:5432/propflow` | **yes** | Full asyncpg connection string |
| `DATABASE_POOL_SIZE` | int | `10` | — | SQLAlchemy async engine pool size |
| `REDIS_URL` | str | `redis://localhost:6379/0` | **yes** | Redis connection URL |
| `META_WHATSAPP_TOKEN` | str | `""` | **yes** | Meta system user permanent access token |
| `META_PHONE_NUMBER_ID` | str | `""` | **yes** | WhatsApp Business phone number ID from Meta console |
| `META_WEBHOOK_VERIFY_TOKEN` | str | `propflow-dev-verify-token` | **yes** | Shared secret for webhook registration |
| `META_API_VERSION` | str | `v18.0` | — | Meta Graph API version |
| `ANTHROPIC_API_KEY` | str | `""` | **yes** | Claude API key |
| `SENTRY_DSN` | str | `""` | — | Sentry project DSN for error tracking |

**Docker note:** When running via `docker-compose`, `DATABASE_URL` and `REDIS_URL` are automatically overridden to use internal hostnames (`postgres:5432`, `redis:6379`). Your `.env` values are used for local development with services exposed on `localhost`.

---

## Demo mode

PropFlow supports a **demo mode** that runs entirely on SQLite — no Docker, no PostgreSQL, no Redis required. This is the default in `.env` for local development and hackathon testing.

### What changes in demo mode

| Feature | Demo (SQLite) | Production (PostgreSQL) |
|---------|--------------|------------------------|
| Database | `sqlite+aiosqlite:///./propflow_demo.db` | `postgresql+asyncpg://...` |
| Connection pool | Disabled (StaticPool) | `pool_size=10, max_overflow=20` |
| Enum storage | VARCHAR strings | Native PostgreSQL ENUM types |
| Array storage | JSON column | Native PostgreSQL ARRAY |
| JSONB columns | JSON column | JSONB (indexed) |
| pgvector | Not available | Enabled via extension |
| Redis | Optional (graceful fallback) | Required |

### Switching between modes

**Demo (default):**
```bash
# .env
DATABASE_URL=sqlite+aiosqlite:///./propflow_demo.db
```

**Production:**
```bash
# .env
DATABASE_URL=postgresql+asyncpg://propflow:propflow@localhost:5432/propflow
```

The migration (`0001_initial_schema.py`) is dialect-aware — it skips PostgreSQL extensions and native enum types when running against SQLite.

### Quick start for demo

Run each command in a **separate terminal tab**:

**Terminal 1 — first-time setup (run once):**
```bash
cd propflow
uv sync
.venv/bin/alembic upgrade head
.venv/bin/python seed_demo.py
```

**Terminal 2 — API server:**
```bash
cd propflow
.venv/bin/uvicorn app.main:app --reload --port 8000
```

**Terminal 3 — ngrok tunnel (exposes localhost to Meta's webhook):**
```bash
ngrok http 8000
# Copy the https://xxxx.ngrok-free.app URL
# Go to Meta Dashboard → WhatsApp → Configuration → Webhook
# Callback URL: https://xxxx.ngrok-free.app/api/v1/webhook
# Verify token:  propflow-wh-k9x2m7  (from .env)
```

`seed_demo.py` inserts:
- 1 landlord
- 1 building (`Musterstraße 12, Berlin`)
- 2 tenants — one onboarded (`Milan Petrović`), one pending onboarding
- 3 contractors (Klaus Wagner · Hans Müller · Ahmed Yilmaz)

---

## Setup and running

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Docker + docker-compose

### Local development (recommended)

```bash
# 1. Clone and install all dependencies
git clone <repo>
cd propflow
uv sync

# 2. Configure environment
cp .env.example .env
# Fill in META_WHATSAPP_TOKEN, META_PHONE_NUMBER_ID, ANTHROPIC_API_KEY, etc.

# 3. Start only the infrastructure (Postgres + Redis)
docker-compose up -d postgres redis

# 4. Wait for health checks to pass
docker-compose ps
# postgres   ...  healthy
# redis      ...  healthy

# 5. Run database migrations
alembic upgrade head

# 6. Start the API with hot reload
uvicorn app.main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

### Production (full Docker)

```bash
cp .env.example .env
# Edit .env with production values

docker-compose up -d
docker-compose exec app alembic upgrade head
```

### Development with Docker hot reload

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The dev override mounts `./app` and `./alembic` as volumes so code changes are reflected immediately without rebuilding.

---

## Database migrations

Alembic is configured for **async SQLAlchemy** via `async_engine_from_config` + `run_sync`. The URL is always sourced from `settings.database_url` (i.e. your `.env`), not from `alembic.ini`.

### Commands

```bash
# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Rollback everything (drops all tables)
alembic downgrade base

# Show migration history
alembic history

# Show current DB revision
alembic current

# Auto-generate a new migration after changing a model
alembic revision --autogenerate -m "add index to tickets"
```

### Migration `0001_initial_schema`

**File:** [alembic/versions/0001_initial_schema.py](alembic/versions/0001_initial_schema.py)

What `upgrade()` does, in order:

1. Enables `uuid-ossp` extension (for `uuid_generate_v4()` server-side default)
2. Enables `vector` extension (pgvector — for future embedding columns)
3. Creates 5 native PostgreSQL ENUM types: `ticketstatus`, `ticketcategory`, `ticketurgency`, `lockedby`, `conversationrole`
4. Creates `landlords` table
5. Creates `buildings` table (FK → landlords)
6. Creates `tenants` table (FK → buildings, landlords) + index on `phone_number`
7. Creates `contractors` table (FK → landlords)
8. Creates `tickets` table (FK → buildings, tenants, contractors) + indexes on `tenant_id`, `building_id`, `status`
9. Creates `conversation_states` table (FK → tickets) + index on `phone_number`

`downgrade()` drops all tables and ENUM types in reverse order.

---

## Testing

```bash
# Run all tests
uv run pytest -v

# Run only onboarding tests
uv run pytest tests/test_onboarding.py -v
```

Tests run **without any live infrastructure**. Two test suites:

### `tests/test_webhook.py` — HTTP layer

**Fixtures:** [tests/conftest.py](tests/conftest.py) patches `app.main.engine` and `app.main.get_redis` so no real Postgres or Redis is needed. The `client` fixture provides `httpx.AsyncClient` via `ASGITransport`.

| Test | What it verifies |
|------|-----------------|
| `test_webhook_verification_success` | Correct verify token → echoes challenge |
| `test_webhook_verification_wrong_token` | Wrong token → 403 |
| `test_webhook_verification_wrong_mode` | `hub.mode != subscribe` → 403 |
| `test_receive_text_message` | Text payload → 200 `{"status":"ok"}` |
| `test_receive_image_message` | Image payload → 200 `{"status":"ok"}` |
| `test_receive_non_whatsapp_payload` | Non-WA object → 200 `{"status":"ignored"}` |
| `test_receive_status_update` | Delivery status update → 200 `{"status":"ok"}` |
| `test_health_check` | `/health` returns `status`, `db`, `redis`, `version` keys |

### `tests/test_onboarding.py` — Onboarding state machine

Uses a **real in-memory SQLite** database (not mocked) + in-memory dict mocking Redis state + mocked `send_text_message`.

| Test | What it verifies |
|------|-----------------|
| `test_unknown_number_gets_rejection` | Unknown phone → "not registered" message |
| `test_pending_tenant_gets_welcome_on_onboarding` | `initiate_onboarding()` → Redis state set + welcome message sent |
| `test_onboarding_reply_saves_name` | "Maria Schmidt" → `tenant.name` updated in DB, Redis cleared, confirmation sent |
| `test_name_too_short_asks_again` | Single-word reply → tenant name stays "Pending", prompt sent again |
| `test_registered_tenant_gets_acknowledgement` | Onboarded tenant → acknowledgement message |

---

## Webhook testing with curl

### Register the webhook (simulates Meta's setup call)

```bash
curl -s "http://localhost:8000/api/v1/webhook?\
hub.mode=subscribe&\
hub.verify_token=propflow-dev-verify-token&\
hub.challenge=my_random_challenge_string"
# → my_random_challenge_string
```

### Simulate a text message from a tenant

```bash
curl -s -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "id": "123",
      "changes": [{
        "value": {
          "messaging_product": "whatsapp",
          "messages": [{
            "from": "+49151234567",
            "id": "wamid.test001",
            "type": "text",
            "text": {"body": "Der Wasserhahn im Bad tropft seit heute Morgen."},
            "timestamp": "1700000000"
          }]
        },
        "field": "messages"
      }]
    }]
  }'
# → {"status":"ok"}
```

### Simulate an image message (photo of the problem)

```bash
curl -s -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "id": "123",
      "changes": [{
        "value": {
          "messaging_product": "whatsapp",
          "messages": [{
            "from": "+49151234567",
            "id": "wamid.img001",
            "type": "image",
            "image": {
              "id": "media_id_abc123",
              "mime_type": "image/jpeg",
              "caption": "Das ist der kaputte Hahn"
            },
            "timestamp": "1700000001"
          }]
        },
        "field": "messages"
      }]
    }]
  }'
# → {"status":"ok"}
```

### Simulate a delivery status update

```bash
curl -s -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "id": "123",
      "changes": [{
        "value": {
          "messaging_product": "whatsapp",
          "statuses": [{
            "id": "wamid.test001",
            "status": "delivered",
            "recipient_id": "+49151234567",
            "timestamp": "1700000005"
          }]
        },
        "field": "messages"
      }]
    }]
  }'
# → {"status":"ok"}
```

### Health check

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
# {
#   "status": "ok",
#   "db": "ok",
#   "redis": "ok",
#   "version": "0.1.0"
# }
```

---

## Design decisions

**Phone number as primary identifier for tenants** — WhatsApp messages arrive with only the sender's phone number. Using it as the lookup key (unique index on `tenants.phone_number`) means a single indexed query resolves who is writing, with no session cookies or JWTs in the messaging path.

**Building-level WhatsApp numbers** — Each building has its own dedicated number. This lets the system know which property a message belongs to *before* looking up the tenant, enabling a building-scoped LangGraph context and cleaner multi-tenancy.

**Immediate 200 + BackgroundTask** — Meta retries if the webhook doesn't respond within 20 seconds. By returning `200` first and processing in a `BackgroundTask`, the AI triage (which may call Claude for image analysis) can take as long as it needs without risking double-delivery of messages.

**Redis + DB dual-write for conversation state** — Redis is the fast path (TTL 24 h, sub-millisecond reads). The `conversation_states` table is the durable fallback so a Redis restart doesn't drop users mid-conversation.

**Optimistic locking with Redis NX** — The `locked_by` field on `Ticket` combined with Redis `SET NX` prevents a landlord's dashboard edit from colliding with an active WhatsApp agent session on the same ticket. The lock auto-expires after 5 minutes if the holder crashes.

**SQLite for demo, PostgreSQL for production** — The migration and all models use generic SQLAlchemy types (`Uuid`, `JSON`) that work on both. Enum columns use `native_enum=False` so SQLite stores them as VARCHAR strings while PostgreSQL can be upgraded to native ENUM types later. The only production feature unavailable in demo mode is pgvector.

**Contractor specialty filtering in Python** — Instead of `WHERE 'plumbing' = ANY(specialties)` (PostgreSQL-only), specialties are stored as a JSON list and filtered in Python. Contractor lists are small (< 50 per landlord) so this is fine, and it keeps the codebase database-agnostic.

**pgvector installed from day one** — The extension is enabled in migration `0001` for PostgreSQL but no vector columns are defined yet. This makes it a zero-cost migration step to add semantic search (e.g. similar past tickets) once embedding generation is implemented.

**SQLAlchemy 2.0 `Mapped[]` style** — All models use `Mapped[T] = mapped_column(...)` instead of the legacy `Column(...)` API. This gives full IDE type-inference, catches nullable mismatches at development time, and is the supported style going forward.

---

## Roadmap

The foundation is in place. Next development steps:

- [ ] **Landlord WhatsApp commands** — parse commands from the landlord's number (e.g. `"New tenant: +381XXXXXXX unit 4B"`) to add tenants directly via WhatsApp without touching the API or seed scripts
- [ ] **LangGraph agent** — wire `_handle_incoming_message` to a stateful graph with nodes: `identify_tenant` → `classify_issue` → `request_photo` → `ai_diagnosis` → `request_landlord_approval` → `dispatch_contractor`
- [ ] **Claude Vision** — call `anthropic.messages.create` with `image` content blocks to analyse photos and produce structured `ai_diagnosis`
- [ ] **Landlord approval flow** — send a template message with approve/reject buttons; handle the interactive reply in the webhook
- [ ] **Contractor dispatch** — send WhatsApp message to contractor; update ticket status to `dispatched`
- [ ] **REST API for dashboard** — CRUD endpoints for landlords, buildings, tenants, contractors; ticket list/detail/update
- [ ] **Authentication** — JWT for dashboard; API key for service-to-service
- [ ] **Ticket embedding** — store `pgvector` embeddings of `description` for similar-ticket lookup
- [ ] **Alembic autogenerate CI check** — fail PR if model changes are not reflected in a new migration
- [ ] **Sentry integration** — enable when `SENTRY_DSN` is set
