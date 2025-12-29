#!/usr/bin/env python3
"""
Hyperliquid Data Feed - Deterministic Approach
===============================================

Let data speak. Follow the math.

Data sources:
1. Trades - detect large trades (whale activity)
2. Funding rate - crowded trade indicator
3. Order flow - buy/sell imbalance
4. Liquidations - forced position closing
"""

import requests
import json
import time
import websocket
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable
from datetime import datetime
from collections import deque

# API endpoints
HL_INFO_API = "https://api.hyperliquid.xyz/info"
HL_WS_URL = "wss://api.hyperliquid.xyz/ws"

# Fee structure
HL_FEE_PCT = 0.035  # 0.035% taker


@dataclass
class Trade:
    """Single trade on Hyperliquid."""
    coin: str
    side: str  # 'B' = buy, 'A' = sell
    price: float
    size: float  # in coin units
    time: int  # timestamp ms
    hash: str

    @property
    def size_usd(self) -> float:
        return self.size * self.price

    @property
    def is_buy(self) -> bool:
        return self.side == 'B'


@dataclass
class FundingRate:
    """Funding rate data."""
    coin: str
    funding_rate: float  # per 8 hours
    mark_price: float
    open_interest: float
    volume_24h: float


@dataclass
class OrderFlowStats:
    """Order flow statistics over a time window."""
    coin: str
    window_seconds: int
    buy_volume: float  # USD
    sell_volume: float  # USD
    trade_count: int
    large_trade_count: int  # trades > threshold
    net_flow: float  # buy - sell
    imbalance_pct: float  # (buy-sell)/(buy+sell) * 100


@dataclass
class Signal:
    """Trading signal from data analysis."""
    coin: str
    direction: str  # 'long' or 'short'
    confidence: float  # 0-1
    reason: str
    data: dict


class HyperliquidDataFeed:
    """
    Real-time data feed from Hyperliquid.

    Collects:
    - All trades
    - Funding rates
    - Order flow statistics
    """

    def __init__(self, coins: List[str] = None):
        self.coins = coins or ['BTC', 'ETH']
        self.session = requests.Session()
        self.session.trust_env = False  # Bypass VPS proxy
        self.session.headers.update({'Content-Type': 'application/json'})

        # Trade history (last N trades per coin)
        self.trades: Dict[str, deque] = {coin: deque(maxlen=1000) for coin in self.coins}

        # Callbacks
        self.on_trade: Optional[Callable[[Trade], None]] = None
        self.on_signal: Optional[Callable[[Signal], None]] = None

        # Large trade threshold (USD)
        self.large_trade_threshold = 50000  # $50k

        # WebSocket
        self.ws = None
        self.ws_thread = None
        self.running = False

    def get_funding_rates(self) -> Dict[str, FundingRate]:
        """Fetch current funding rates for all coins."""
        try:
            # Get asset contexts (funding, volume, OI)
            resp = self.session.post(
                HL_INFO_API,
                json={"type": "metaAndAssetCtxs"},
                timeout=10
            )
            data = resp.json()

            rates = {}
            # data[0] = meta (universe), data[1] = asset contexts
            meta = data[0]['universe']
            contexts = data[1]

            for i, asset in enumerate(meta):
                coin = asset['name']
                if coin in self.coins:
                    ctx = contexts[i]
                    rates[coin] = FundingRate(
                        coin=coin,
                        funding_rate=float(ctx.get('funding', 0)),
                        mark_price=float(ctx.get('markPx', 0)),
                        open_interest=float(ctx.get('openInterest', 0)),
                        volume_24h=float(ctx.get('dayNtlVlm', 0))
                    )

            return rates
        except Exception as e:
            print(f"[ERROR] Failed to fetch funding rates: {e}")
            return {}

    def get_recent_trades(self, coin: str, limit: int = 100) -> List[Trade]:
        """Fetch recent trades from REST API."""
        try:
            resp = self.session.post(
                HL_INFO_API,
                json={"type": "recentTrades", "coin": coin},
                timeout=10
            )
            data = resp.json()

            trades = []
            for t in data[:limit]:
                trades.append(Trade(
                    coin=t['coin'],
                    side=t['side'],
                    price=float(t['px']),
                    size=float(t['sz']),
                    time=t['time'],
                    hash=t['hash']
                ))

            return trades
        except Exception as e:
            print(f"[ERROR] Failed to fetch trades for {coin}: {e}")
            return []

    def calculate_order_flow(self, coin: str, window_seconds: int = 60) -> OrderFlowStats:
        """Calculate order flow statistics for a time window."""
        now = int(time.time() * 1000)
        cutoff = now - (window_seconds * 1000)

        trades = [t for t in self.trades.get(coin, []) if t.time >= cutoff]

        buy_volume = sum(t.size_usd for t in trades if t.is_buy)
        sell_volume = sum(t.size_usd for t in trades if not t.is_buy)
        total_volume = buy_volume + sell_volume

        large_trades = [t for t in trades if t.size_usd >= self.large_trade_threshold]

        imbalance = 0
        if total_volume > 0:
            imbalance = (buy_volume - sell_volume) / total_volume * 100

        return OrderFlowStats(
            coin=coin,
            window_seconds=window_seconds,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            trade_count=len(trades),
            large_trade_count=len(large_trades),
            net_flow=buy_volume - sell_volume,
            imbalance_pct=imbalance
        )

    def analyze_for_signals(self, coin: str) -> Optional[Signal]:
        """
        Analyze data for trading signals.

        Signal conditions:
        1. Large trade detected (> threshold)
        2. High funding rate (crowded trade)
        3. Strong order flow imbalance
        """
        # Get current data
        flow = self.calculate_order_flow(coin, window_seconds=60)
        rates = self.get_funding_rates()
        funding = rates.get(coin)

        signals = []

        # Signal 1: Large trade in last minute
        recent_large = [t for t in self.trades.get(coin, [])
                       if t.size_usd >= self.large_trade_threshold
                       and t.time >= int(time.time() * 1000) - 60000]

        if recent_large:
            last_large = recent_large[-1]
            direction = 'long' if last_large.is_buy else 'short'
            signals.append(Signal(
                coin=coin,
                direction=direction,
                confidence=0.6,
                reason=f"Large {last_large.side} trade: ${last_large.size_usd:,.0f}",
                data={'trade': last_large.__dict__}
            ))

        # Signal 2: Extreme funding rate (contrarian)
        if funding and abs(funding.funding_rate) > 0.01:  # > 1% per 8h
            # High positive funding = too many longs = short
            # High negative funding = too many shorts = long
            direction = 'short' if funding.funding_rate > 0 else 'long'
            signals.append(Signal(
                coin=coin,
                direction=direction,
                confidence=0.5,
                reason=f"Extreme funding: {funding.funding_rate*100:.2f}%",
                data={'funding': funding.__dict__}
            ))

        # Signal 3: Strong order flow imbalance
        if abs(flow.imbalance_pct) > 30 and flow.trade_count > 10:
            direction = 'long' if flow.imbalance_pct > 0 else 'short'
            signals.append(Signal(
                coin=coin,
                direction=direction,
                confidence=0.4,
                reason=f"Flow imbalance: {flow.imbalance_pct:+.1f}%",
                data={'flow': flow.__dict__}
            ))

        # Return highest confidence signal
        if signals:
            return max(signals, key=lambda s: s.confidence)
        return None

    def _on_ws_message(self, ws, message):
        """Handle WebSocket message."""
        try:
            data = json.loads(message)

            if data.get('channel') == 'trades':
                for t in data.get('data', []):
                    trade = Trade(
                        coin=t['coin'],
                        side=t['side'],
                        price=float(t['px']),
                        size=float(t['sz']),
                        time=t['time'],
                        hash=t['hash']
                    )

                    # Store trade
                    if trade.coin in self.trades:
                        self.trades[trade.coin].append(trade)

                    # Callback
                    if self.on_trade:
                        self.on_trade(trade)

                    # Check for large trade
                    if trade.size_usd >= self.large_trade_threshold:
                        print(f"[WHALE] {trade.coin} {'BUY' if trade.is_buy else 'SELL'} "
                              f"${trade.size_usd:,.0f} @ {trade.price:,.2f}")

                        # Generate signal
                        signal = self.analyze_for_signals(trade.coin)
                        if signal and self.on_signal:
                            self.on_signal(signal)

        except Exception as e:
            print(f"[WS ERROR] {e}")

    def _on_ws_open(self, ws):
        """Subscribe to trade streams."""
        for coin in self.coins:
            ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {"type": "trades", "coin": coin}
            }))
        print(f"[WS] Subscribed to trades for {self.coins}")

    def _on_ws_error(self, ws, error):
        print(f"[WS ERROR] {error}")

    def _on_ws_close(self, ws, close_status, close_msg):
        print(f"[WS] Closed: {close_status} {close_msg}")

    def start_websocket(self):
        """Start WebSocket connection for real-time trades."""
        self.running = True
        self.ws = websocket.WebSocketApp(
            HL_WS_URL,
            on_message=self._on_ws_message,
            on_open=self._on_ws_open,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close
        )
        self.ws_thread = threading.Thread(target=self.ws.run_forever)
        self.ws_thread.daemon = True
        self.ws_thread.start()

    def stop(self):
        """Stop WebSocket connection."""
        self.running = False
        if self.ws:
            self.ws.close()


def print_market_snapshot():
    """Print current market snapshot."""
    feed = HyperliquidDataFeed(coins=['BTC', 'ETH', 'SOL'])

    print("=" * 70)
    print("HYPERLIQUID MARKET SNAPSHOT")
    print("=" * 70)

    # Funding rates
    rates = feed.get_funding_rates()
    print("\n[FUNDING RATES]")
    for coin, rate in rates.items():
        print(f"  {coin}: {rate.funding_rate*100:+.4f}% (8h) | "
              f"OI: ${rate.open_interest:,.0f} | "
              f"Vol: ${rate.volume_24h:,.0f}")

    # Recent trades
    print("\n[RECENT LARGE TRADES]")
    for coin in feed.coins:
        trades = feed.get_recent_trades(coin, limit=50)
        large = [t for t in trades if t.size_usd >= 10000]

        for t in large[:5]:
            print(f"  {coin} {'BUY' if t.is_buy else 'SELL'} ${t.size_usd:,.0f} @ {t.price:,.2f}")

    print("=" * 70)


def run_live_monitor(duration_seconds: int = 300):
    """Run live trade monitor."""
    feed = HyperliquidDataFeed(coins=['BTC', 'ETH'])

    # Set thresholds
    feed.large_trade_threshold = 25000  # $25k

    print("=" * 70)
    print("HYPERLIQUID LIVE MONITOR")
    print("=" * 70)
    print(f"Watching: {feed.coins}")
    print(f"Large trade threshold: ${feed.large_trade_threshold:,}")
    print(f"Duration: {duration_seconds}s")
    print("=" * 70)

    # Callbacks
    def on_signal(signal: Signal):
        print(f"\n[SIGNAL] {signal.coin} {signal.direction.upper()} "
              f"(confidence: {signal.confidence:.0%})")
        print(f"  Reason: {signal.reason}")

    feed.on_signal = on_signal

    # Start WebSocket
    feed.start_websocket()

    try:
        start = time.time()
        while time.time() - start < duration_seconds:
            time.sleep(10)

            # Print flow stats every 10 seconds
            for coin in feed.coins:
                flow = feed.calculate_order_flow(coin, window_seconds=60)
                if flow.trade_count > 0:
                    print(f"[{coin}] Trades: {flow.trade_count} | "
                          f"Buy: ${flow.buy_volume:,.0f} | "
                          f"Sell: ${flow.sell_volume:,.0f} | "
                          f"Imbalance: {flow.imbalance_pct:+.1f}%")

    except KeyboardInterrupt:
        print("\nStopped by user")
    finally:
        feed.stop()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "live":
        duration = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        run_live_monitor(duration)
    else:
        print_market_snapshot()
