# PropRelay

PropRelay is an AI-powered property management platform for landlords, built at the Garaža Hackathon (May 2026). Tenants report maintenance problems over WhatsApp, a LangGraph agent built on Claude triages the request, asks for photos and diagnoses the issue, and the landlord approves or rejects the repair with a one-tap reply. Approved jobs are dispatched to a matching contractor, and every party gets status updates along the way.

## How it works

1. **Tenant writes on WhatsApp.** The webhook returns `200` immediately and processes the message in a background task, staying inside Meta's 20-second limit.
2. **The agent takes over.** A LangGraph workflow identifies the intent, requests a photo, diagnoses the issue and decides whether it needs self-help instructions or a repair.
3. **The landlord approves.** Serious issues pause the graph (checkpointed in Redis) until the landlord replies.
4. **A contractor is dispatched.** The agent finds a contractor with the right specialty and confirms the job.

Conversation state lives in Redis with a PostgreSQL fallback, and optimistic locking keeps WhatsApp and dashboard edits from overwriting the same ticket. The full graph is in [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md).

## Tech stack

| Layer | Technology | Version |
|

## Quick start

```bash
uv sync
cp .env.example .env          # fill in WhatsApp and Anthropic credentials
docker-compose up -d postgres redis
alembic upgrade head
uvicorn app.main:app --reload # http://localhost:8000/docs
```

For a SQLite demo without Postgres, see [Configuration and demo mode](docs/configuration.md). Full setup, migrations and tests are in [Development](docs/development.md).

## Documentation

| Topic | Document |
|---|---|
| LangGraph orchestration | [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md) |
| Architecture, request flow, webhook routing | [docs/architecture.md](docs/architecture.md) |
| Tenant onboarding and contractor service | [docs/onboarding-and-contractors.md](docs/onboarding-and-contractors.md) |
| Project structure | [docs/project-structure.md](docs/project-structure.md) |
| Database models | [docs/database.md](docs/database.md) |
| API, WhatsApp and Redis services | [docs/services-and-api.md](docs/services-and-api.md) |
| Configuration and demo mode | [docs/configuration.md](docs/configuration.md) |
| Development, migrations and testing | [docs/development.md](docs/development.md) |
| Design decisions | [docs/design-decisions.md](docs/design-decisions.md) |
| Roadmap | [docs/roadmap.md](docs/roadmap.md) |
