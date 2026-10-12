# Architecture

← [Back to README](../README.md)

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

The stub comment in [app/api/v1/webhook.py](../app/api/v1/webhook.py) marks exactly where the agent router connects:

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
