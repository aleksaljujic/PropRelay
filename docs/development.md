# Development, migrations and testing

← [Back to README](../README.md)

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

**File:** [alembic/versions/0001_initial_schema.py](../alembic/versions/0001_initial_schema.py)

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

**Fixtures:** [tests/conftest.py](../tests/conftest.py) patches `app.main.engine` and `app.main.get_redis` so no real Postgres or Redis is needed. The `client` fixture provides `httpx.AsyncClient` via `ASGITransport`.

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
