#!/usr/bin/env python3
"""
C++ Order Book Bridge - High-Speed Order Book Access

PURE DATA. NO MOCK. MATH NEVER LIES.

This module provides order book data from the C++ caching service,
replacing the slow Python CCXT implementation.

Performance:
    - Python CCXT: ~100ms per request (network bound)
    - C++ Cache:   <1ms read from JSON file (pre-cached)

The C++ orderbook_service runs in background, pre-caching order books
from all exchanges via REST. This module reads the cached data.
"""

import json
import os
import time
import subprocess
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from pathlib import Path


# Default cache file location (same as C++ service output)
DEFAULT_CACHE_PATH = "/tmp/orderbooks.json"


@dataclass
class OrderBookSnapshot:
    """Order book state for an exchange (compatible with old OrderFlow)."""
    exchange: str
    timestamp: datetime
    best_bid: float
    best_ask: float
    bid_volume: float
    ask_volume: float
    spread_pct: float

    @property
    def sell_pressure(self) -> float:
        """Ratio of ask volume to bid volume. >1 = more sellers."""
        if self.bid_volume == 0:
            return 999.0
        return self.ask_volume / self.bid_volume


class CppOrderBook:
    """
    High-speed order book access via C++ cache.

    Drop-in replacement for OrderFlow class, but reads from
    C++ pre-cached data instead of making CCXT API calls.
    """

    # Exchange name mapping (normalize to lowercase)
    EXCHANGE_ALIASES = {
        'binance': 'binanceus',
        'huobi': 'htx',
        'gate.io': 'gateio',
        'crypto.com': 'cryptocom',
    }

    def __init__(self, cache_path: str = DEFAULT_CACHE_PATH):
        self.cache_path = cache_path
        self._cache: Dict = {}
        self._cache_time: float = 0
        self._cache_max_age: float = 1.0  # Reload cache if older than 1 second
        self._service_process: Optional[subprocess.Popen] = None
        self._service_thread: Optional[threading.Thread] = None
        self.running = False

    def _normalize_exchange(self, exchange: str) -> str:
        """Normalize exchange name to match C++ cache keys."""
        ex = exchange.lower().replace('.', '').replace('-', '')
        return self.EXCHANGE_ALIASES.get(ex, ex)

    def _load_cache(self) -> bool:
        """Load order book cache from JSON file."""
        now = time.time()

        # Check if cache is fresh enough
        if now - self._cache_time < self._cache_max_age and self._cache:
            return True

        # Check if file exists
        if not os.path.exists(self.cache_path):
            return False

        try:
            with open(self.cache_path, 'r') as f:
                self._cache = json.load(f)
            self._cache_time = now
            return True
        except (json.JSONDecodeError, IOError) as e:
            print(f"[CPP_ORDERBOOK] Cache read error: {e}")
            return False

    def _get_exchange_data(self, exchange: str) -> Optional[Dict]:
        """Get cached data for an exchange."""
        if not self._load_cache():
            return None

        ex = self._normalize_exchange(exchange)
        exchanges = self._cache.get('exchanges', {})

        # Try exact match first
        if ex in exchanges:
            return exchanges[ex]

        # Try fuzzy match
        for key in exchanges:
            if key.replace('-', '').replace('_', '') == ex:
                return exchanges[key]

        return None

    def fetch_order_book(self, exchange: str) -> Optional[OrderBookSnapshot]:
        """
        Get order book snapshot for an exchange.
        Compatible with old OrderFlow.fetch_order_book().
        """
        data = self._get_exchange_data(exchange)
        if not data or not data.get('valid', False):
            return None

        bids = data.get('bids', [])
        asks = data.get('asks', [])

        if not bids or not asks:
            return None

        # Calculate volumes (top 20 levels for pressure detection)
        bid_volume = sum(level[1] for level in bids[:20])
        ask_volume = sum(level[1] for level in asks[:20])

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        spread_pct = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0

        return OrderBookSnapshot(
            exchange=exchange,
            timestamp=datetime.now(timezone.utc),
            best_bid=best_bid,
            best_ask=best_ask,
            bid_volume=bid_volume,
            ask_volume=ask_volume,
            spread_pct=spread_pct,
        )

    def fetch_full_order_book(self, exchange: str, depth: int = 50) -> Optional[Dict]:
        """
        Get full order book depth for price impact calculation.
        Compatible with old OrderFlow.fetch_full_order_book().

        Returns:
            {
                'bids': [(price, volume), ...],
                'asks': [(price, volume), ...],
                'timestamp': datetime
            }
        """
        data = self._get_exchange_data(exchange)
        if not data or not data.get('valid', False):
            return None

        bids = data.get('bids', [])[:depth]
        asks = data.get('asks', [])[:depth]

        if not bids or not asks:
            return None

        return {
            'bids': [(level[0], level[1]) for level in bids],
            'asks': [(level[0], level[1]) for level in asks],
            'timestamp': datetime.now(timezone.utc)
        }

    def get_bids(self, exchange: str) -> List[Tuple[float, float]]:
        """Get bid levels (price, volume) for an exchange."""
        book = self.fetch_full_order_book(exchange)
        return book['bids'] if book else []

    def get_asks(self, exchange: str) -> List[Tuple[float, float]]:
        """Get ask levels (price, volume) for an exchange."""
        book = self.fetch_full_order_book(exchange)
        return book['asks'] if book else []

    def has_sell_pressure(self, exchange: str, min_btc: float = 1.0) -> bool:
        """Check if exchange has significant sell pressure."""
        book = self.fetch_order_book(exchange)
        if not book:
            return False
        return book.ask_volume >= min_btc and book.sell_pressure > 1.0

    def has_buy_pressure(self, exchange: str, min_btc: float = 1.0) -> bool:
        """Check if exchange has significant buy pressure."""
        book = self.fetch_order_book(exchange)
        if not book:
            return False
        return book.bid_volume >= min_btc and book.sell_pressure < 1.0

    def get_total_depth(self, exchange: str, side: str = 'bids', levels: int = 50) -> float:
        """Get total volume available at given number of levels."""
        book = self.fetch_full_order_book(exchange, levels)
        if not book:
            return 0.0
        data = book.get(side, [])
        return sum(level[1] for level in data[:levels])

    def get_net_flow(self, exchange: str, seconds: int = 60) -> float:
        """
        Get net buy/sell flow.

        NOTE: C++ cache doesn't track trade flow, so this returns 0.
        For deterministic trading, we rely on order book pressure instead.
        """
        # Trade flow not available from cache - use order book pressure
        book = self.fetch_order_book(exchange)
        if not book:
            return 0.0

        # Estimate from order book imbalance
        if book.sell_pressure > 1.0:
            return -(book.ask_volume - book.bid_volume)  # Negative = selling
        else:
            return book.bid_volume - book.ask_volume  # Positive = buying

    def get_recent_sells(self, exchange: str, seconds: int = 60, min_btc: float = 0.5) -> List:
        """Get recent sell trades (not available from cache)."""
        return []  # Trade history not cached

    def get_recent_buys(self, exchange: str, seconds: int = 60, min_btc: float = 0.5) -> List:
        """Get recent buy trades (not available from cache)."""
        return []  # Trade history not cached

    def is_cache_valid(self) -> bool:
        """Check if cache file exists and is recent."""
        if not os.path.exists(self.cache_path):
            return False

        try:
            stat = os.stat(self.cache_path)
            age = time.time() - stat.st_mtime
            return age < 10  # Cache should be < 10 seconds old
        except OSError:
            return False

    def get_cache_status(self) -> Dict:
        """Get cache status information."""
        if not self._load_cache():
            return {'valid': False, 'exchanges': 0, 'age_ms': -1}

        exchanges = self._cache.get('exchanges', {})
        timestamp = self._cache.get('timestamp', 0)
        age_ms = int(time.time() * 1000) - timestamp if timestamp else -1

        return {
            'valid': True,
            'exchanges': len(exchanges),
            'exchange_list': list(exchanges.keys()),
            'age_ms': age_ms,
            'cache_path': self.cache_path
        }

    def start(self):
        """
        Start the C++ orderbook service (if not running).
        Called for compatibility with old OrderFlow.start().
        """
        if self.running:
            return

        # Check if service is already providing data
        if self.is_cache_valid():
            print("[CPP_ORDERBOOK] Cache already available, using existing service")
            self.running = True
            return

        # Try to start the service
        service_paths = [
            '/root/sovereign/cpp_runner/build/orderbook_service',
            './build/orderbook_service',
            '../cpp_runner/build/orderbook_service',
        ]

        service_path = None
        for path in service_paths:
            if os.path.exists(path):
                service_path = path
                break

        if not service_path:
            print("[CPP_ORDERBOOK] Warning: orderbook_service not found, cache may be stale")
            self.running = True
            return

        try:
            self._service_process = subprocess.Popen(
                [service_path, '--output', self.cache_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[CPP_ORDERBOOK] Started orderbook_service (PID {self._service_process.pid})")
            self.running = True

            # Wait for initial cache
            for _ in range(20):  # Wait up to 2 seconds
                if self.is_cache_valid():
                    break
                time.sleep(0.1)

        except Exception as e:
            print(f"[CPP_ORDERBOOK] Failed to start service: {e}")
            self.running = True  # Continue anyway with possibly stale cache

    def stop(self):
        """Stop the C++ orderbook service."""
        self.running = False
        if self._service_process:
            self._service_process.terminate()
            self._service_process.wait(timeout=5)
            self._service_process = None

    def get_coverage(self) -> Dict:
        """Get exchange coverage stats (compatible with OrderFlow)."""
        status = self.get_cache_status()
        return {
            'initialized': status.get('exchanges', 0),
            'active': status.get('exchanges', 0),
            'failed': 0,
            'exchanges': status.get('exchange_list', []),
            'failed_list': [],
            'source': 'cpp_cache'
        }

    def get_status(self) -> Dict:
        """Get current order flow status for all exchanges."""
        if not self._load_cache():
            return {}

        status = {}
        exchanges = self._cache.get('exchanges', {})

        for exchange, data in exchanges.items():
            if not data.get('valid', False):
                continue

            best_bid = data.get('best_bid', 0)
            best_ask = data.get('best_ask', 0)
            bid_vol = data.get('bid_depth', 0)
            ask_vol = data.get('ask_depth', 0)

            spread_pct = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0
            sell_pressure = ask_vol / bid_vol if bid_vol > 0 else 999

            status[exchange] = {
                'bid': f"${best_bid:,.2f}",
                'ask': f"${best_ask:,.2f}",
                'spread': f"{spread_pct:.3f}%",
                'bid_vol': f"{bid_vol:.2f} BTC",
                'ask_vol': f"{ask_vol:.2f} BTC",
                'sell_pressure': f"{sell_pressure:.2f}x",
                'recent_sells': 0,  # Not tracked in cache
                'confirmed': sell_pressure > 1.0,
                'age_ms': data.get('age_ms', -1),
            }

        return status


# Backwards compatibility alias
OrderFlow = CppOrderBook


def main():
    """Test C++ order book bridge."""
    print("=" * 70)
    print("C++ ORDER BOOK BRIDGE - TEST")
    print("=" * 70)
    print()

    book = CppOrderBook()

    # Check cache status
    status = book.get_cache_status()
    print(f"Cache Status: {status}")
    print()

    if not status['valid']:
        print("Cache not available. Starting service...")
        book.start()
        time.sleep(2)
        status = book.get_cache_status()
        print(f"Cache Status: {status}")
        print()

    # Fetch order books
    exchanges = ['gemini', 'deribit', 'poloniex', 'mexc', 'zebpay', 'phemex']

    print(f"{'Exchange':<12} {'Bid':>12} {'Ask':>12} {'Spread':>8} {'Bid Vol':>10} {'Ask Vol':>10} {'Pressure':>10}")
    print("-" * 80)

    for ex in exchanges:
        snapshot = book.fetch_order_book(ex)
        if snapshot:
            pressure_str = f"{snapshot.sell_pressure:.2f}x"
            if snapshot.sell_pressure > 1.0:
                pressure_str += " SELL"
            print(f"{ex:<12} ${snapshot.best_bid:>10,.2f} ${snapshot.best_ask:>10,.2f} "
                  f"{snapshot.spread_pct:>7.3f}% {snapshot.bid_volume:>9.2f} "
                  f"{snapshot.ask_volume:>9.2f} {pressure_str:>10}")
        else:
            print(f"{ex:<12} -- not available --")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
