"""
RedisEventBus — multi-instance pub/sub backend (Phase 9).

Implements the same EventBusInterface as the in-process LocalEventBus, but routes
events through Redis pub/sub so that any number of app instances behind a load
balancer share one logical event stream. Selected via settings.pubsub_backend
== "redis". redis is imported lazily so the dependency is only required when the
Redis backend is actually enabled.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

import structlog

from app.events.event_protocol import EventBusInterface, EventHandler

logger = structlog.get_logger(__name__)


class RedisEventBus(EventBusInterface):
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis: Any = None
        self._pubsub: Any = None
        self._subscribers: dict[str, dict[str, EventHandler]] = defaultdict(dict)
        self._reader_tasks: dict[str, asyncio.Task] = {}
        self._sub_counter = 0
        self._lock = asyncio.Lock()
        self._running = False

    async def start(self) -> None:
        try:
            import redis.asyncio as aioredis  # lazy import
        except ImportError as exc:  # pragma: no cover - depends on deployment
            raise RuntimeError(
                "pubsub_backend='redis' but the 'redis' package is not installed. "
                "Install redis>=4.2 or set pubsub_backend='memory'."
            ) from exc
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        await self._redis.ping()
        self._running = True
        logger.info("redis_event_bus.started", url=self._redis_url)

    async def shutdown(self) -> None:
        self._running = False
        for task in self._reader_tasks.values():
            task.cancel()
        await asyncio.gather(*self._reader_tasks.values(), return_exceptions=True)
        self._reader_tasks.clear()
        if self._redis is not None:
            await self._redis.aclose()
        logger.info("redis_event_bus.shutdown")

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        if not self._running or self._redis is None:
            logger.warning("redis_event_bus.publish_while_stopped", channel=channel)
            return
        await self._redis.publish(channel, json.dumps(event, sort_keys=True, separators=(",", ":"), default=str))

    async def subscribe(self, channel: str, handler: EventHandler) -> str:
        async with self._lock:
            self._sub_counter += 1
            sub_id = f"sub_{channel}_{self._sub_counter}"
            self._subscribers[channel][sub_id] = handler
            if channel not in self._reader_tasks:
                self._reader_tasks[channel] = asyncio.create_task(
                    self._reader(channel), name=f"redis_reader_{channel}"
                )
            return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        async with self._lock:
            for subs in self._subscribers.values():
                subs.pop(subscription_id, None)

    async def flush_channel(self, channel: str) -> None:
        # Redis pub/sub is fire-and-forget; nothing is buffered server-side.
        return

    async def _reader(self, channel: str) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if not self._running:
                    break
                if message.get("type") != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                except (TypeError, ValueError):
                    continue
                for handler in list(self._subscribers.get(channel, {}).values()):
                    try:
                        await handler(event)
                    except Exception as exc:
                        logger.error("redis_event_bus.handler_error", channel=channel, error=str(exc))
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
