# LangGraph Maintenance Orchestration

## Graph visualization

```mermaid
graph TD
    START([START]) --> identify_intent[identify_intent]
    identify_intent -->|maintenance| request_photo[request_photo]
    identify_intent -->|complaint| log_complaint[log_complaint]
    identify_intent -->|admin| forward_to_landlord[forward_to_landlord]
    request_photo -->|interrupt: photo| PAUSE1{{⏸ Redis checkpoint}}
    PAUSE1 -->|tenant sends image| diagnose_issue[diagnose_issue]
    request_photo --> diagnose_issue
    diagnose_issue -->|minor| self_help[self_help]
    diagnose_issue -->|serious| prepare_approval[prepare_approval]
    prepare_approval --> notify_landlord[notify_landlord]
    notify_landlord -->|interrupt: approval| PAUSE2{{⏸ Redis checkpoint}}
    PAUSE2 -->|landlord YES| find_contractor[find_contractor]
    PAUSE2 -->|landlord NO| notify_rejection[notify_rejection]
    find_contractor --> dispatch_contractor[dispatch_contractor]
    dispatch_contractor -->|interrupt: confirm| PAUSE3{{⏸ Redis checkpoint}}
    PAUSE3 --> END([END])
    self_help --> END
    log_complaint --> END
    forward_to_landlord --> END
    notify_rejection --> END
```

## Architecture

| Layer | Responsibility |
|-------|----------------|
| `app/graph/builder.py` | LangGraph StateGraph definition |
| `app/nodes/` | One interaction step per node |
| `app/graph/orchestrator.py` | Event dispatch + interrupt/resume |
| `app/storage/redis_checkpoint.py` | Durable graph state |
| `app/services/claude_service.py` | Isolated LLM reasoning (Pydantic JSON) |
| `app/workers/timeout_worker.py` | Event-driven reminders/escalations |

## Local development

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env

# 3. Start infrastructure
docker-compose up -d postgres redis

# 4. Migrate + seed
uv run alembic upgrade head
uv run python seed_demo.py

# 5. Run API (starts timeout worker automatically)
uv run uvicorn app.main:app --reload --port 8000

# 6. Inspect workflow state
curl http://localhost:8000/api/v1/workflows/<tenant_phone>
```

## Design principles

- **LangGraph orchestrates** — Claude never decides the next node
- **One step per node** — no blocking loops
- **Redis checkpoints** — multi-turn resume across messages
- **interrupt()** — human-in-the-loop at photo, approval, contractor confirm
- **Timeouts** — Redis sorted-set scheduler (24h / 30min / 15min)

Generate PNG from Mermaid: paste the diagram into https://mermaid.live
