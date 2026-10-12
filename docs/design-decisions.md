# Design decisions

← [Back to README](../README.md)


**Phone number as primary identifier for tenants** — WhatsApp messages arrive with only the sender's phone number. Using it as the lookup key (unique index on `tenants.phone_number`) means a single indexed query resolves who is writing, with no session cookies or JWTs in the messaging path.

**Building-level WhatsApp numbers** — Each building has its own dedicated number. This lets the system know which property a message belongs to *before* looking up the tenant, enabling a building-scoped LangGraph context and cleaner multi-tenancy.

**Immediate 200 + BackgroundTask** — Meta retries if the webhook doesn't respond within 20 seconds. By returning `200` first and processing in a `BackgroundTask`, the AI triage (which may call Claude for image analysis) can take as long as it needs without risking double-delivery of messages.

**Redis + DB dual-write for conversation state** — Redis is the fast path (TTL 24 h, sub-millisecond reads). The `conversation_states` table is the durable fallback so a Redis restart doesn't drop users mid-conversation.

**Optimistic locking with Redis NX** — The `locked_by` field on `Ticket` combined with Redis `SET NX` prevents a landlord's dashboard edit from colliding with an active WhatsApp agent session on the same ticket. The lock auto-expires after 5 minutes if the holder crashes.

**SQLite for demo, PostgreSQL for production** — The migration and all models use generic SQLAlchemy types (`Uuid`, `JSON`) that work on both. Enum columns use `native_enum=False` so SQLite stores them as VARCHAR strings while PostgreSQL can be upgraded to native ENUM types later. The only production feature unavailable in demo mode is pgvector.

**Contractor specialty filtering in Python** — Instead of `WHERE 'plumbing' = ANY(specialties)` (PostgreSQL-only), specialties are stored as a JSON list and filtered in Python. Contractor lists are small (< 50 per landlord) so this is fine, and it keeps the codebase database-agnostic.

**pgvector installed from day one** — The extension is enabled in migration `0001` for PostgreSQL but no vector columns are defined yet. This makes it a zero-cost migration step to add semantic search (e.g. similar past tickets) once embedding generation is implemented.

**SQLAlchemy 2.0 `Mapped[]` style** — All models use `Mapped[T] = mapped_column(...)` instead of the legacy `Column(...)` API. This gives full IDE type-inference, catches nullable mismatches at development time, and is the supported style going forward.
