# API, WhatsApp and Redis

← [Back to README](../README.md)

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

**File:** [app/services/whatsapp.py](../app/services/whatsapp.py)

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

**File:** [app/core/redis.py](../app/core/redis.py)

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
