"""
Sovereign Trader - Event Types
==============================

Event-driven architecture matching LMAX Disruptor pattern.
All components communicate through immutable events.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Dict, Any
import time

from .types import Exchange, Side, OrderBook, Order, Trade, Position


class EventType(Enum):
    """All event types in the system."""
    # Data events
    ORDERBOOK_UPDATE = auto()
    TRADE_TICK = auto()

    # Blockchain events
    DEPOSIT_DETECTED = auto()
    WITHDRAWAL_DETECTED = auto()

    # Signal events
    SIGNAL_GENERATED = auto()
    SIGNAL_CONFIRMED = auto()
    SIGNAL_EXPIRED = auto()

    # Order events
    ORDER_SUBMITTED = auto()
    ORDER_FILLED = auto()
    ORDER_CANCELLED = auto()
    ORDER_REJECTED = auto()

    # Position events
    POSITION_OPENED = auto()
    POSITION_UPDATED = auto()
    POSITION_CLOSED = auto()

    # System events
    SYSTEM_STARTED = auto()
    SYSTEM_STOPPED = auto()
    HEARTBEAT = auto()
    ERROR = auto()


@dataclass(frozen=True)
class Event:
    """Base event class - immutable."""
    event_type: EventType
    timestamp_ns: int
    source: str

    @staticmethod
    def now_ns() -> int:
        return time.time_ns()


@dataclass(frozen=True)
class DepositDetectedEvent(Event):
    """Blockchain deposit detected."""
    txid: str
    exchange: Exchange
    amount_btc: float
    from_address: str
    to_address: str
    confirmations: int

    def __init__(self, txid: str, exchange: Exchange, amount_btc: float,
                 from_address: str, to_address: str, confirmations: int = 0):
        object.__setattr__(self, 'event_type', EventType.DEPOSIT_DETECTED)
        object.__setattr__(self, 'timestamp_ns', time.time_ns())
        object.__setattr__(self, 'source', 'blockchain')
        object.__setattr__(self, 'txid', txid)
        object.__setattr__(self, 'exchange', exchange)
        object.__setattr__(self, 'amount_btc', amount_btc)
        object.__setattr__(self, 'from_address', from_address)
        object.__setattr__(self, 'to_address', to_address)
        object.__setattr__(self, 'confirmations', confirmations)


@dataclass(frozen=True)
class SignalGeneratedEvent(Event):
    """Trading signal generated."""
    signal_id: str
    exchange: Exchange
    symbol: str
    side: Side
    expected_impact_pct: float
    total_fees_pct: float
    net_profit_pct: float
    confidence: float
    trigger_deposit_btc: Optional[float] = None

    def __init__(self, signal_id: str, exchange: Exchange, symbol: str,
                 side: Side, expected_impact_pct: float, total_fees_pct: float,
                 confidence: float, trigger_deposit_btc: float = None):
        object.__setattr__(self, 'event_type', EventType.SIGNAL_GENERATED)
        object.__setattr__(self, 'timestamp_ns', time.time_ns())
        object.__setattr__(self, 'source', 'signals')
        object.__setattr__(self, 'signal_id', signal_id)
        object.__setattr__(self, 'exchange', exchange)
        object.__setattr__(self, 'symbol', symbol)
        object.__setattr__(self, 'side', side)
        object.__setattr__(self, 'expected_impact_pct', expected_impact_pct)
        object.__setattr__(self, 'total_fees_pct', total_fees_pct)
        object.__setattr__(self, 'net_profit_pct', expected_impact_pct - total_fees_pct)
        object.__setattr__(self, 'confidence', confidence)
        object.__setattr__(self, 'trigger_deposit_btc', trigger_deposit_btc)


@dataclass(frozen=True)
class OrderbookUpdateEvent(Event):
    """Orderbook update received."""
    orderbook: OrderBook

    def __init__(self, orderbook: OrderBook):
        object.__setattr__(self, 'event_type', EventType.ORDERBOOK_UPDATE)
        object.__setattr__(self, 'timestamp_ns', time.time_ns())
        object.__setattr__(self, 'source', 'data')
        object.__setattr__(self, 'orderbook', orderbook)


@dataclass(frozen=True)
class OrderFilledEvent(Event):
    """Order filled."""
    order: Order
    trade: Trade

    def __init__(self, order: Order, trade: Trade):
        object.__setattr__(self, 'event_type', EventType.ORDER_FILLED)
        object.__setattr__(self, 'timestamp_ns', time.time_ns())
        object.__setattr__(self, 'source', 'execution')
        object.__setattr__(self, 'order', order)
        object.__setattr__(self, 'trade', trade)
