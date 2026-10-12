# Roadmap

← [Back to README](../README.md)


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
