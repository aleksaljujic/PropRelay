# Project structure

← [Back to README](../README.md)


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
