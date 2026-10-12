# Configuration and demo mode

← [Back to README](../README.md)

## Configuration

**File:** [app/config.py](../app/config.py)

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
