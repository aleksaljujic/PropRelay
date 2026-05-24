"""
Redis-backed LangGraph checkpoint saver.

Persists graph execution state so multi-turn workflows resume exactly
where they paused — survives process restarts and horizontal scaling.
"""
from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import structlog
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.core.redis import get_redis

logger = structlog.get_logger(__name__)

_CHECKPOINT_PREFIX = "lg:ckpt"
_WRITES_PREFIX = "lg:writes"
_DEFAULT_TTL = 86_400 * 7  # 7 days — active workflows outlive 24 h photo wait


def _encode_typed(data: tuple[str, bytes]) -> list[str]:
    """JSON-safe encoding for serde.dumps_typed() output."""
    typ, blob = data
    return [typ, base64.b64encode(blob).decode("ascii")]


def _decode_typed(data: list[str]) -> tuple[str, bytes]:
    """Reverse _encode_typed for serde.loads_typed()."""
    typ, b64 = data
    return typ, base64.b64decode(b64)


class RedisCheckpointSaver(BaseCheckpointSaver):
    """
    Async Redis checkpointer for LangGraph.

    Keys:
      lg:ckpt:{thread_id}       — latest checkpoint blob
      lg:writes:{thread_id}     — pending channel writes (if any)
    """

    serde = JsonPlusSerializer()

    def __init__(self, ttl: int = _DEFAULT_TTL) -> None:
        super().__init__()
        self.ttl = ttl

    # ── Sync stubs (not used — app is fully async) ────────────────────────

    def get_tuple(self, config: dict) -> CheckpointTuple | None:
        raise NotImplementedError("Use aget_tuple in async context")

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> dict:
        raise NotImplementedError("Use aput in async context")

    def list(
        self,
        config: dict,
        *,
        filter: dict[str, Any] | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        raise NotImplementedError("Use alist in async context")

    # ── Async API ─────────────────────────────────────────────────────────

    def _thread_id(self, config: dict) -> str:
        return config["configurable"]["thread_id"]

    def _checkpoint_key(self, thread_id: str) -> str:
        return f"{_CHECKPOINT_PREFIX}:{thread_id}"

    def _writes_key(self, thread_id: str) -> str:
        return f"{_WRITES_PREFIX}:{thread_id}"

    async def aget_tuple(self, config: dict) -> CheckpointTuple | None:
        thread_id = self._thread_id(config)
        redis = await get_redis()
        raw = await redis.get(self._checkpoint_key(thread_id))
        if raw is None:
            return None

        try:
            payload = json.loads(raw)
            checkpoint = self.serde.loads_typed(_decode_typed(payload["checkpoint"]))
            metadata = payload.get("metadata", {})
            parent_config = payload.get("parent_config")
            return CheckpointTuple(
                config=config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
            )
        except Exception as exc:
            logger.error("Failed to load checkpoint", thread_id=thread_id, error=str(exc))
            return None

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> dict:
        thread_id = self._thread_id(config)
        redis = await get_redis()

        checkpoint_id = checkpoint.get("id") if isinstance(checkpoint, dict) else getattr(checkpoint, "id", None)
        updated_config = {
            **config,
            "configurable": {
                **config.get("configurable", {}),
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            },
        }

        payload = {
            "checkpoint": _encode_typed(self.serde.dumps_typed(checkpoint)),
            "metadata": metadata,
            "parent_config": config,
        }
        await redis.setex(
            self._checkpoint_key(thread_id),
            self.ttl,
            json.dumps(payload, default=str),
        )
        logger.debug("Checkpoint saved", thread_id=thread_id, checkpoint_id=checkpoint_id)
        return updated_config

    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = self._thread_id(config)
        redis = await get_redis()
        key = self._writes_key(thread_id)
        existing_raw = await redis.get(key)
        existing: list[dict] = json.loads(existing_raw) if existing_raw else []
        existing.append({"task_id": task_id, "writes": writes, "task_path": task_path})
        await redis.setex(key, self.ttl, json.dumps(existing, default=str))

    async def alist(
        self,
        config: dict,
        *,
        filter: dict[str, Any] | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        tup = await self.aget_tuple(config)
        if tup is not None:
            yield tup

    async def adelete_thread(self, thread_id: str) -> None:
        """Remove all checkpoint data for a completed workflow."""
        redis = await get_redis()
        await redis.delete(self._checkpoint_key(thread_id), self._writes_key(thread_id))
        logger.info("Checkpoint deleted", thread_id=thread_id)
