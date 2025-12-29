"""
Sovereign Trader - Core Types
=============================

Matching NautilusTrader type patterns with nanosecond precision.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional
import time


class Exchange(Enum):
    """Supported exchanges."""
    # CEX
    COINBASE = auto()
    OKX = auto()
    KRAKEN = auto()
    GEMINI = auto()
    BITSTAMP = auto()
    HTX = auto()
    KUCOIN = auto()
    GATE = auto()
    MEXC = auto()
    BITGET = auto()
    # DEX
    HYPERLIQUID = auto()
    DYDX = auto()
    INJECTIVE = auto()
    UNKNOWN = auto()


class Side(Enum):
    """Order side."""
    BUY = auto()
    SELL = auto()


class OrderType(Enum):
    """Order types."""
    MARKET = auto()
    LIMIT = auto()
    STOP_LOSS = auto()
    TAKE_PROFIT = auto()


class OrderStatus(Enum):
    """Order status."""
    PENDING = auto()
    SUBMITTED = auto()
    FILLED = auto()
    PARTIALLY_FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()


@dataclass
class PriceLevel:
    """Single orderbook price level."""
    price: float
    size: float


@dataclass
class OrderBook:
    """Orderbook with nanosecond timestamp."""
    exchange: Exchange
    symbol: str
    bids: List[PriceLevel]
    asks: List[PriceLevel]
    timestamp_ns: int
    parse_latency_ns: int = 0

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_pct(self) -> Optional[float]:
        if self.best_bid and self.spread:
            return (self.spread / self.best_bid) * 100
        return None


@dataclass
class Order:
    """Trading order."""
    id: str
    exchange: Exchange
    symbol: str
    side: Side
    order_type: OrderType
    size: float
    price: Optional[float]
    status: OrderStatus
    timestamp_ns: int
    filled_size: float = 0.0
    filled_price: Optional[float] = None


@dataclass
class Trade:
    """Executed trade."""
    id: str
    exchange: Exchange
    symbol: str
    side: Side
    size: float
    price: float
    fee: float
    fee_currency: str
    timestamp_ns: int


@dataclass
class Position:
    """Open position."""
    exchange: Exchange
    symbol: str
    side: Side
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    timestamp_ns: int


def now_ns() -> int:
    """Get current time in nanoseconds."""
    return time.time_ns()
