"""
Local Event Bus — async pub/sub for internal event routing.

Uses asyncio.Queue internally but abstracts the interface so it can be
replaced with Redis Streams, Kafka, or NATS in the future with minimal rewrites.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any
import structlog
from app.events.event_protocol import EventBusInterface, EventHandler

logger = structlog.get_logger(__name__)

# local EventHandler and EventBusInterface definitions removed in favor of event_protocol.py


class LocalEventBus(EventBusInterface):
    """
    Local asyncio-based event bus for development.
    Channel-based routing with subscriber groups.
    """

    def __init__(self, max_queue_size: int = 10_000):
        self._subscribers: dict[str, dict[str, EventHandler]] = defaultdict(dict)
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._max_queue_size = max_queue_size
        self._running = False
        self._sub_counter = 0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the event bus."""
        self._running = True
        logger.info("event_bus.started")

    async def shutdown(self) -> None:
        """Gracefully shutdown the event bus."""
        self._running = False
        for task in self._workers.values():
            task.cancel()
        await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._queues.clear()
        self._subscribers.clear()
        logger.info("event_bus.shutdown")

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        """Publish an event to a channel."""
        if not self._running:
            logger.warning("event_bus.publish_while_stopped", channel=channel)
            return

        # Ensure channel worker exists
        if channel not in self._queues:
            await self._ensure_channel(channel)

        try:
            self._queues[channel].put_nowait(event)
            logger.debug(
                "event_bus.published",
                channel=channel,
                event_type=event.get("type", "unknown"),
            )
        except asyncio.QueueFull:
            logger.error(
                "event_bus.queue_full",
                channel=channel,
                max_size=self._max_queue_size,
            )

    async def subscribe(self, channel: str, handler: EventHandler) -> str:
        """Subscribe a handler to a channel. Returns subscription ID."""
        async with self._lock:
            self._sub_counter += 1
            sub_id = f"sub_{channel}_{self._sub_counter}"
            self._subscribers[channel][sub_id] = handler

            # Ensure channel worker exists
            if channel not in self._queues:
                await self._ensure_channel(channel)

            logger.info("event_bus.subscribed", channel=channel, sub_id=sub_id)
            return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription."""
        async with self._lock:
            for channel, subs in self._subscribers.items():
                if subscription_id in subs:
                    del subs[subscription_id]
                    logger.info(
                        "event_bus.unsubscribed",
                        channel=channel,
                        sub_id=subscription_id,
                    )
                    return

    async def flush_channel(self, channel: str) -> None:
        """Flush all pending events in a channel (used during interruption)."""
        if channel in self._queues:
            queue = self._queues[channel]
            flushed = 0
            while not queue.empty():
                try:
                    queue.get_nowait()
                    flushed += 1
                except asyncio.QueueEmpty:
                    break
            logger.info("event_bus.channel_flushed", channel=channel, flushed=flushed)

    async def _ensure_channel(self, channel: str) -> None:
        """Create queue and worker for a channel if they don't exist."""
        if channel not in self._queues:
            self._queues[channel] = asyncio.Queue(maxsize=self._max_queue_size)
            self._workers[channel] = asyncio.create_task(
                self._channel_worker(channel),
                name=f"event_bus_worker_{channel}",
            )

    async def _channel_worker(self, channel: str) -> None:
        """Background worker that dispatches events to subscribers."""
        queue = self._queues[channel]
        logger.info("event_bus.worker_started", channel=channel)

        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Dispatch to all subscribers
            handlers = list(self._subscribers.get(channel, {}).values())
            for handler in handlers:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(
                        "event_bus.handler_error",
                        channel=channel,
                        error=str(e),
                        exc_info=True,
                    )

        logger.info("event_bus.worker_stopped", channel=channel)


# ── Singleton / backend factory (Phase 9) ────────────────────────

_event_bus: EventBusInterface | None = None


def get_event_bus() -> EventBusInterface:
    """
    Get or create the global event bus. The backend is selected by
    settings.pubsub_backend: 'memory' (in-process, single instance, default) or
    'redis' (multi-instance pub/sub). Both implement EventBusInterface, so all
    callers (gateway, routes) are backend-agnostic.
    """
    global _event_bus
    if _event_bus is None:
        from app.config.settings import get_settings

        backend = (get_settings().pubsub_backend or "memory").lower()
        if backend == "redis":
            from app.events.redis_event_bus import RedisEventBus

            _event_bus = RedisEventBus(get_settings().redis_url)
            logger.info("event_bus.backend_selected", backend="redis")
        else:
            _event_bus = LocalEventBus()
            logger.info("event_bus.backend_selected", backend="memory")
    return _event_bus
