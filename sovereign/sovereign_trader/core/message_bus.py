"""
Sovereign Trader - MessageBus
=============================

LMAX Disruptor-inspired event bus for nanosecond messaging.
Single-threaded, lock-free design matching NautilusTrader pattern.

Key features:
- Publish/subscribe pattern
- Request/response capability
- Command/event messaging
- Deterministic event ordering (single-threaded)

Reference: https://martinfowler.com/articles/lmax.html
"""

from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict
from dataclasses import dataclass
import time
import logging

from ..model.events import Event, EventType

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    """Event subscription."""
    event_type: EventType
    callback: Callable[[Event], None]
    priority: int = 0  # Higher = called first


class MessageBus:
    """
    LMAX-inspired event bus.

    Design principles from LMAX Disruptor:
    - Single-threaded execution (no locks needed)
    - Deterministic message ordering
    - Immutable events
    - Broadcast semantics (all subscribers receive)

    52ns latency target for message passing.
    """

    def __init__(self):
        """Initialize the message bus."""
        self._subscriptions: Dict[EventType, List[Subscription]] = defaultdict(list)
        self._handlers: Dict[str, Callable] = {}
        self._event_count: int = 0
        self._start_time_ns: int = time.time_ns()
        self._last_event_ns: int = 0

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None],
                  priority: int = 0) -> None:
        """
        Subscribe to an event type.

        Args:
            event_type: The type of event to subscribe to
            callback: Function to call when event occurs
            priority: Higher priority callbacks are called first
        """
        sub = Subscription(event_type, callback, priority)
        self._subscriptions[event_type].append(sub)
        # Sort by priority (descending)
        self._subscriptions[event_type].sort(key=lambda s: -s.priority)
        logger.debug(f"Subscribed to {event_type.name}, total: {len(self._subscriptions[event_type])}")

    def unsubscribe(self, event_type: EventType, callback: Callable) -> bool:
        """
        Unsubscribe from an event type.

        Returns True if subscription was found and removed.
        """
        subs = self._subscriptions[event_type]
        for i, sub in enumerate(subs):
            if sub.callback == callback:
                subs.pop(i)
                return True
        return False

    def publish(self, event: Event) -> int:
        """
        Publish an event to all subscribers.

        LMAX pattern: Events are processed synchronously in order.
        This ensures deterministic behavior for backtesting.

        Returns: Number of callbacks invoked
        """
        start_ns = time.time_ns()
        count = 0

        subscribers = self._subscriptions.get(event.event_type, [])
        for sub in subscribers:
            try:
                sub.callback(event)
                count += 1
            except Exception as e:
                logger.error(f"Callback error for {event.event_type.name}: {e}")

        self._event_count += 1
        self._last_event_ns = time.time_ns()

        latency_ns = self._last_event_ns - start_ns
        if latency_ns > 1000000:  # > 1ms is slow
            logger.warning(f"Slow event dispatch: {latency_ns/1000:.1f}us for {event.event_type.name}")

        return count

    def register_handler(self, name: str, handler: Callable) -> None:
        """
        Register a named request handler.

        Used for request/response pattern.
        """
        self._handlers[name] = handler

    def request(self, handler_name: str, *args, **kwargs) -> Any:
        """
        Send a request to a named handler.

        Returns the handler's response.
        """
        handler = self._handlers.get(handler_name)
        if handler is None:
            raise KeyError(f"No handler registered: {handler_name}")
        return handler(*args, **kwargs)

    def has_subscribers(self, event_type: EventType) -> bool:
        """Check if event type has any subscribers."""
        return len(self._subscriptions.get(event_type, [])) > 0

    def subscriber_count(self, event_type: EventType) -> int:
        """Get number of subscribers for event type."""
        return len(self._subscriptions.get(event_type, []))

    @property
    def event_count(self) -> int:
        """Total events published since start."""
        return self._event_count

    @property
    def uptime_seconds(self) -> float:
        """Uptime in seconds."""
        return (time.time_ns() - self._start_time_ns) / 1e9

    def stats(self) -> Dict[str, Any]:
        """Get bus statistics."""
        return {
            "event_count": self._event_count,
            "uptime_seconds": self.uptime_seconds,
            "events_per_second": self._event_count / max(self.uptime_seconds, 0.001),
            "subscriptions": {
                et.name: len(subs) for et, subs in self._subscriptions.items()
            },
            "handlers": list(self._handlers.keys()),
        }


# Global singleton for simple usage
_default_bus: Optional[MessageBus] = None


def get_message_bus() -> MessageBus:
    """Get the default message bus singleton."""
    global _default_bus
    if _default_bus is None:
        _default_bus = MessageBus()
    return _default_bus


def reset_message_bus() -> None:
    """Reset the default message bus (for testing)."""
    global _default_bus
    _default_bus = None
