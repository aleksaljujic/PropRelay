FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./

RUN uv pip install --system -r pyproject.toml 2>/dev/null || uv pip install --system \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.30.0" \
    "sqlalchemy[asyncio]>=2.0.0" \
    "asyncpg>=0.29.0" \
    "aiosqlite>=0.20.0" \
    "alembic>=1.13.0" \
    "pgvector>=0.3.0" \
    "redis[asyncio]>=5.0.0" \
    "httpx>=0.27.0" \
    "pydantic>=2.7.0" \
    "pydantic-settings>=2.3.0" \
    "anthropic>=0.30.0" \
    "langgraph>=0.2.60" \
    "langgraph-checkpoint>=2.0.0" \
    "python-multipart>=0.0.9" \
    "structlog>=24.1.0"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
