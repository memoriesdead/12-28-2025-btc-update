#!/usr/bin/env python3
"""
Hyperliquid Paper Trading - Simple Math Approach
=================================================

Strategy: impact > 2×fees = trade

Hyperliquid fee: 0.035% (taker)
Required impact: 0.07% (2×fees)

Uses Hyperliquid public API for orderbook data.
"""

import requests
import time
import json
from dataclasses import dataclass
from typing import Optional, List, Tuple
from datetime import datetime

# Hyperliquid config
HL_API = "https://api.hyperliquid.xyz/info"
HL_FEE_PCT = 0.035  # 0.035% taker fee
MIN_IMPACT_MULTIPLE = 2.0  # Need 2× fees to profit
REQUIRED_IMPACT_PCT = HL_FEE_PCT * MIN_IMPACT_MULTIPLE  # 0.07%

# Frankfurt proxy for VPS
FRANKFURT_PROXY = "http://141.147.58.130:8888"


@dataclass
class OrderbookLevel:
    price: float
    size: float  # BTC
    count: int


@dataclass
class Orderbook:
    coin: str
    timestamp: int
    bids: List[OrderbookLevel]  # Descending price
    asks: List[OrderbookLevel]  # Ascending price

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread_pct(self) -> float:
        if self.best_bid == 0:
            return 0
        return (self.best_ask - self.best_bid) / self.best_bid * 100


@dataclass
class ImpactResult:
    side: str  # 'buy' or 'sell'
    size_btc: float
    avg_fill_price: float
    worst_price: float
    impact_pct: float  # Price impact percentage
    profitable: bool  # impact > 2×fees


@dataclass
class PaperPosition:
    side: str  # 'long' or 'short'
    entry_price: float
    size_btc: float
    size_usd: float
    leverage: int
    timestamp: datetime
    expected_impact_pct: float


@dataclass
class PaperTrade:
    position: PaperPosition
    exit_price: float
    pnl_pct: float
    pnl_usd: float
    exit_time: datetime
    reason: str


class HyperliquidDataFeed:
    """Fetches orderbook data from Hyperliquid API."""

    def __init__(self, use_proxy: bool = False):
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        # Disable all proxies (VPS has global proxy that blocks Hyperliquid)
        self.session.trust_env = False
        if use_proxy:
            self.session.proxies = {
                'http': FRANKFURT_PROXY,
                'https': FRANKFURT_PROXY
            }

    def get_orderbook(self, coin: str = "BTC") -> Optional[Orderbook]:
        """Fetch L2 orderbook for a coin."""
        try:
            resp = self.session.post(
                HL_API,
                json={"type": "l2Book", "coin": coin},
                timeout=5
            )
            data = resp.json()

            # Parse bids (first array)
            bids = []
            for level in data.get("levels", [[]])[0]:
                bids.append(OrderbookLevel(
                    price=float(level["px"]),
                    size=float(level["sz"]),
                    count=int(level["n"])
                ))

            # Parse asks (second array)
            asks = []
            for level in data.get("levels", [[], []])[1]:
                asks.append(OrderbookLevel(
                    price=float(level["px"]),
                    size=float(level["sz"]),
                    count=int(level["n"])
                ))

            return Orderbook(
                coin=data["coin"],
                timestamp=data["time"],
                bids=bids,
                asks=asks
            )
        except Exception as e:
            print(f"[ERROR] Failed to fetch orderbook: {e}")
            return None

    def get_mid_price(self, coin: str = "BTC") -> float:
        """Get current mid price."""
        ob = self.get_orderbook(coin)
        return ob.mid_price if ob else 0


class ImpactCalculator:
    """Calculate market impact for order sizes."""

    @staticmethod
    def calculate_buy_impact(orderbook: Orderbook, size_btc: float) -> ImpactResult:
        """Calculate impact of buying size_btc."""
        remaining = size_btc
        total_cost = 0
        worst_price = 0

        for level in orderbook.asks:
            if remaining <= 0:
                break
            fill_size = min(remaining, level.size)
            total_cost += fill_size * level.price
            remaining -= fill_size
            worst_price = level.price

        if remaining > 0:
            # Not enough liquidity
            return ImpactResult(
                side='buy',
                size_btc=size_btc,
                avg_fill_price=0,
                worst_price=0,
                impact_pct=999,
                profitable=False
            )

        avg_price = total_cost / size_btc
        impact_pct = (avg_price - orderbook.best_ask) / orderbook.best_ask * 100

        return ImpactResult(
            side='buy',
            size_btc=size_btc,
            avg_fill_price=avg_price,
            worst_price=worst_price,
            impact_pct=impact_pct,
            profitable=impact_pct >= REQUIRED_IMPACT_PCT
        )

    @staticmethod
    def calculate_sell_impact(orderbook: Orderbook, size_btc: float) -> ImpactResult:
        """Calculate impact of selling size_btc."""
        remaining = size_btc
        total_proceeds = 0
        worst_price = 0

        for level in orderbook.bids:
            if remaining <= 0:
                break
            fill_size = min(remaining, level.size)
            total_proceeds += fill_size * level.price
            remaining -= fill_size
            worst_price = level.price

        if remaining > 0:
            return ImpactResult(
                side='sell',
                size_btc=size_btc,
                avg_fill_price=0,
                worst_price=0,
                impact_pct=999,
                profitable=False
            )

        avg_price = total_proceeds / size_btc
        impact_pct = (orderbook.best_bid - avg_price) / orderbook.best_bid * 100

        return ImpactResult(
            side='sell',
            size_btc=size_btc,
            avg_fill_price=avg_price,
            worst_price=worst_price,
            impact_pct=impact_pct,
            profitable=impact_pct >= REQUIRED_IMPACT_PCT
        )


class PaperTrader:
    """Simple paper trading engine."""

    def __init__(self, capital_usd: float = 100, leverage: int = 10):
        self.capital_usd = capital_usd
        self.leverage = leverage
        self.position: Optional[PaperPosition] = None
        self.trades: List[PaperTrade] = []
        self.pnl_usd = 0

    def can_trade(self) -> bool:
        """Check if we can open a new position."""
        return self.position is None

    def open_long(self, price: float, size_usd: float, expected_impact: float) -> PaperPosition:
        """Open a long position."""
        size_btc = size_usd / price
        self.position = PaperPosition(
            side='long',
            entry_price=price,
            size_btc=size_btc,
            size_usd=size_usd,
            leverage=self.leverage,
            timestamp=datetime.now(),
            expected_impact_pct=expected_impact
        )
        return self.position

    def open_short(self, price: float, size_usd: float, expected_impact: float) -> PaperPosition:
        """Open a short position."""
        size_btc = size_usd / price
        self.position = PaperPosition(
            side='short',
            entry_price=price,
            size_btc=size_btc,
            size_usd=size_usd,
            leverage=self.leverage,
            timestamp=datetime.now(),
            expected_impact_pct=expected_impact
        )
        return self.position

    def close_position(self, exit_price: float, reason: str = "manual") -> Optional[PaperTrade]:
        """Close current position and record trade."""
        if not self.position:
            return None

        pos = self.position

        # Calculate P&L
        if pos.side == 'long':
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        else:  # short
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

        # Apply leverage
        pnl_pct_leveraged = pnl_pct * self.leverage

        # Subtract fees (entry + exit)
        pnl_pct_after_fees = pnl_pct_leveraged - (HL_FEE_PCT * 2)

        # Calculate USD P&L
        pnl_usd = pos.size_usd * (pnl_pct_after_fees / 100)

        trade = PaperTrade(
            position=pos,
            exit_price=exit_price,
            pnl_pct=pnl_pct_after_fees,
            pnl_usd=pnl_usd,
            exit_time=datetime.now(),
            reason=reason
        )

        self.trades.append(trade)
        self.pnl_usd += pnl_usd
        self.capital_usd += pnl_usd
        self.position = None

        return trade


def run_paper_trading(duration_seconds: int = 600, capital: float = 10, leverage: int = 10):
    """
    Run paper trading for specified duration.

    Args:
        duration_seconds: How long to run (default 10 minutes)
        capital: Starting capital in USD
        leverage: Leverage to use
    """
    print("=" * 60)
    print("HYPERLIQUID PAPER TRADING - Simple Math Approach")
    print("=" * 60)
    print(f"Capital: ${capital}")
    print(f"Leverage: {leverage}x")
    print(f"Fee: {HL_FEE_PCT}%")
    print(f"Required impact: {REQUIRED_IMPACT_PCT}% (2×fees)")
    print(f"Duration: {duration_seconds}s")
    print("=" * 60)

    feed = HyperliquidDataFeed()
    calc = ImpactCalculator()
    trader = PaperTrader(capital_usd=capital, leverage=leverage)

    start_time = time.time()
    check_count = 0

    # Position sizing: 25% of capital per trade
    position_size_usd = capital * 0.25 * leverage

    try:
        while time.time() - start_time < duration_seconds:
            check_count += 1

            # Get orderbook
            ob = feed.get_orderbook("BTC")
            if not ob:
                time.sleep(1)
                continue

            # Calculate position size in BTC
            size_btc = position_size_usd / ob.mid_price

            # Calculate impact for both sides
            buy_impact = calc.calculate_buy_impact(ob, size_btc)
            sell_impact = calc.calculate_sell_impact(ob, size_btc)

            # Status update every 10 checks
            if check_count % 10 == 0:
                print(f"\n[Check #{check_count}] BTC: ${ob.mid_price:,.0f} | "
                      f"Spread: {ob.spread_pct:.4f}% | "
                      f"Buy impact: {buy_impact.impact_pct:.4f}% | "
                      f"Sell impact: {sell_impact.impact_pct:.4f}%")

            # Trading logic
            if trader.can_trade():
                # Look for trading opportunity
                # Note: In real trading, we'd look for large flows causing impact
                # For paper trading, we check if impact exceeds threshold

                if buy_impact.profitable:
                    pos = trader.open_long(ob.best_ask, position_size_usd / leverage, buy_impact.impact_pct)
                    print(f"\n[LONG] Opened at ${pos.entry_price:,.2f} | "
                          f"Size: {pos.size_btc:.6f} BTC | "
                          f"Impact: {buy_impact.impact_pct:.4f}%")

                elif sell_impact.profitable:
                    pos = trader.open_short(ob.best_bid, position_size_usd / leverage, sell_impact.impact_pct)
                    print(f"\n[SHORT] Opened at ${pos.entry_price:,.2f} | "
                          f"Size: {pos.size_btc:.6f} BTC | "
                          f"Impact: {sell_impact.impact_pct:.4f}%")

            else:
                # Check exit conditions
                pos = trader.position
                current_price = ob.mid_price

                if pos.side == 'long':
                    pnl_pct = (current_price - pos.entry_price) / pos.entry_price * 100 * leverage
                else:
                    pnl_pct = (pos.entry_price - current_price) / pos.entry_price * 100 * leverage

                # Exit conditions
                take_profit = pnl_pct >= 0.5  # 0.5% profit (after leverage)
                stop_loss = pnl_pct <= -0.25  # 0.25% loss

                if take_profit:
                    trade = trader.close_position(current_price, "take_profit")
                    print(f"\n[CLOSED - TP] P&L: {trade.pnl_pct:+.4f}% (${trade.pnl_usd:+.4f})")

                elif stop_loss:
                    trade = trader.close_position(current_price, "stop_loss")
                    print(f"\n[CLOSED - SL] P&L: {trade.pnl_pct:+.4f}% (${trade.pnl_usd:+.4f})")

            time.sleep(1)  # Check every second

    except KeyboardInterrupt:
        print("\n\nStopped by user.")

    # Close any open position
    if trader.position:
        ob = feed.get_orderbook("BTC")
        if ob:
            trade = trader.close_position(ob.mid_price, "session_end")
            print(f"\n[CLOSED - End] P&L: {trade.pnl_pct:+.4f}% (${trade.pnl_usd:+.4f})")

    # Summary
    print("\n" + "=" * 60)
    print("SESSION SUMMARY")
    print("=" * 60)
    print(f"Duration: {int(time.time() - start_time)}s")
    print(f"Checks: {check_count}")
    print(f"Trades: {len(trader.trades)}")
    print(f"Total P&L: ${trader.pnl_usd:+.4f}")
    print(f"Final Capital: ${trader.capital_usd:.2f}")
    print(f"Return: {(trader.capital_usd - capital) / capital * 100:+.2f}%")

    if trader.trades:
        winners = sum(1 for t in trader.trades if t.pnl_usd > 0)
        print(f"Win Rate: {winners}/{len(trader.trades)} ({winners/len(trader.trades)*100:.0f}%)")

    print("=" * 60)


if __name__ == "__main__":
    import sys

    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 300  # 5 minutes default
    capital = float(sys.argv[2]) if len(sys.argv) > 2 else 10
    leverage = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    run_paper_trading(duration, capital, leverage)
