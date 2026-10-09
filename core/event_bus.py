
import asyncio
import uuid
from typing import Callable, Dict, List, Awaitable
from core.types import OrchestrationEvent


class IEventBus:
    """Interface contract for the harness event bus."""

    async def publish(self, topic: str, event: OrchestrationEvent) -> None:
        """Publish an event to all subscribers of the given topic."""
        raise NotImplementedError

    def subscribe(self, topic: str, callback: Callable[[OrchestrationEvent], Awaitable[None]]) -> str:
        """Subscribe to a topic. Returns a subscription_id for later unsubscribe."""
        raise NotImplementedError

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by its ID."""
        raise NotImplementedError


class InMemoryEventBus(IEventBus):
    """Production implementation: async in-memory topic event bus."""

    def __init__(self):
        self._subscriptions: Dict[str, Dict[str, Callable]] = {}  # topic -> {sub_id -> callback}

    async def publish(self, topic: str, event: OrchestrationEvent) -> None:
        callbacks = self._subscriptions.get(topic, {})
        tasks = [callback(event) for callback in callbacks.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def subscribe(self, topic: str, callback: Callable[[OrchestrationEvent], Awaitable[None]]) -> str:
        if topic not in self._subscriptions:
            self._subscriptions[topic] = {}
        sub_id = f"sub_{uuid.uuid4().hex[:12]}"
        self._subscriptions[topic][sub_id] = callback
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        for topic_subs in self._subscriptions.values():
            topic_subs.pop(subscription_id, None)

