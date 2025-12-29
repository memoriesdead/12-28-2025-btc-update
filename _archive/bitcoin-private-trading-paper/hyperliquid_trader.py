#!/usr/bin/env python3
"""
Hyperliquid Paper Trading - Data-Driven Approach
=================================================

Strategy: Follow the flow. Let data speak.

Signals:
1. Order flow imbalance > 30% = trade in direction of flow
2. Large trades > $50k = follow the whale
3. Extreme funding > 0.5% = contrarian (too crowded)

Math:
- Fee: 0.035% per trade
- Required edge: 0.07% (2×fees)
- With 10x leverage: 0.007% move = breakeven
"""

import requests
import time
import json
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime

# Config
HL_API = "https://api.hyperliquid.xyz/info"
HL_FEE_PCT = 0.035
REQUIRED_EDGE_PCT = HL_FEE_PCT * 2  # 0.07%


@dataclass
class MarketState:
    coin: str
    price: float
    buy_volume: float
    sell_volume: float
    imbalance_pct: float
    funding_rate: float
    large_trades: int
    timestamp: datetime


@dataclass
class Position:
    coin: str
    side: str  # 'long' or 'short'
    entry_price: float
    size_usd: float
    leverage: int
    entry_time: datetime
    reason: str


@dataclass
class Trade:
    position: Position
    exit_price: float
    pnl_pct: float
    pnl_usd: float
    exit_time: datetime
    exit_reason: str


class HyperliquidTrader:
    """Paper trader using Hyperliquid data."""

    def __init__(self, capital: float = 10, leverage: int = 10):
        self.capital = capital
        self.leverage = leverage
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.pnl = 0

        self.session = requests.Session()
        self.session.trust_env = False

        # Signal thresholds (tuned based on data)
        self.imbalance_threshold = 60  # 60% imbalance (was 30 - too noisy)
        self.large_trade_threshold = 25000  # $25k (lower to catch more whales)
        self.funding_threshold = 0.003  # 0.3% per 8h
        self.min_hold_seconds = 30  # Minimum hold time to avoid chop

        # Position sizing
        self.position_size_pct = 0.25  # 25% of capital per trade

    def get_market_state(self, coin: str) -> Optional[MarketState]:
        """Fetch current market state."""
        try:
            # Get trades
            resp = self.session.post(
                HL_API,
                json={'type': 'recentTrades', 'coin': coin},
                timeout=10
            )
            trades = resp.json()

            # Calculate flow
            buys = [t for t in trades if t['side'] == 'B']
            sells = [t for t in trades if t['side'] == 'A']

            buy_vol = sum(float(t['sz']) * float(t['px']) for t in buys)
            sell_vol = sum(float(t['sz']) * float(t['px']) for t in sells)
            total_vol = buy_vol + sell_vol

            imbalance = 0
            if total_vol > 0:
                imbalance = (buy_vol - sell_vol) / total_vol * 100

            # Large trades
            large = len([t for t in trades if float(t['sz']) * float(t['px']) > self.large_trade_threshold])

            # Get price
            price = float(trades[0]['px']) if trades else 0

            # Get funding
            resp2 = self.session.post(
                HL_API,
                json={'type': 'metaAndAssetCtxs'},
                timeout=10
            )
            data = resp2.json()
            funding = 0
            for i, asset in enumerate(data[0]['universe']):
                if asset['name'] == coin:
                    funding = float(data[1][i].get('funding', 0))
                    break

            return MarketState(
                coin=coin,
                price=price,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                imbalance_pct=imbalance,
                funding_rate=funding,
                large_trades=large,
                timestamp=datetime.now()
            )

        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    def should_trade(self, state: MarketState) -> Optional[str]:
        """
        Determine if we should trade based on market state.
        Returns 'long', 'short', or None.

        Priority:
        1. Whale trades + flow alignment = strongest signal
        2. Extreme funding (contrarian) = medium signal
        3. Very strong flow alone = weaker signal
        """
        direction = None
        reasons = []
        score = 0

        # Signal 1: Whale trades (strongest when aligned with flow)
        if state.large_trades > 0 and abs(state.imbalance_pct) > 40:
            direction = 'long' if state.imbalance_pct > 0 else 'short'
            reasons.append(f"{state.large_trades} whale(s) + flow {state.imbalance_pct:+.0f}%")
            score += 3

        # Signal 2: Extreme funding (contrarian)
        elif abs(state.funding_rate) > self.funding_threshold:
            direction = 'short' if state.funding_rate > 0 else 'long'
            reasons.append(f"Funding {state.funding_rate*100:+.3f}% (contrarian)")
            score += 2

        # Signal 3: Very strong flow alone (needs higher threshold)
        elif abs(state.imbalance_pct) > 80:  # Only trade 80%+ imbalance without whale
            direction = 'long' if state.imbalance_pct > 0 else 'short'
            reasons.append(f"Strong flow {state.imbalance_pct:+.0f}%")
            score += 1

        if score >= 1 and direction:
            return direction, "; ".join(reasons)
        return None, None

    def open_position(self, coin: str, direction: str, price: float, reason: str):
        """Open a new position."""
        size = self.capital * self.position_size_pct
        self.position = Position(
            coin=coin,
            side=direction,
            entry_price=price,
            size_usd=size,
            leverage=self.leverage,
            entry_time=datetime.now(),
            reason=reason
        )
        print(f"\n[OPEN {direction.upper()}] {coin} @ ${price:,.2f}")
        print(f"  Size: ${size:.2f} ({self.leverage}x)")
        print(f"  Reason: {reason}")

    def close_position(self, price: float, reason: str) -> Trade:
        """Close current position."""
        pos = self.position

        # Calculate P&L
        if pos.side == 'long':
            price_change_pct = (price - pos.entry_price) / pos.entry_price * 100
        else:
            price_change_pct = (pos.entry_price - price) / pos.entry_price * 100

        # Apply leverage and subtract fees
        pnl_pct = (price_change_pct * self.leverage) - (HL_FEE_PCT * 2)
        pnl_usd = pos.size_usd * (pnl_pct / 100)

        trade = Trade(
            position=pos,
            exit_price=price,
            pnl_pct=pnl_pct,
            pnl_usd=pnl_usd,
            exit_time=datetime.now(),
            exit_reason=reason
        )

        self.trades.append(trade)
        self.pnl += pnl_usd
        self.capital += pnl_usd
        self.position = None

        print(f"\n[CLOSE] {pos.coin} @ ${price:,.2f}")
        print(f"  P&L: {pnl_pct:+.3f}% (${pnl_usd:+.4f})")
        print(f"  Reason: {reason}")

        return trade

    def check_exit(self, state: MarketState) -> Optional[str]:
        """Check if we should exit position."""
        if not self.position:
            return None

        pos = self.position
        price = state.price

        # Calculate hold time
        hold_seconds = (datetime.now() - pos.entry_time).total_seconds()

        # Calculate current P&L
        if pos.side == 'long':
            pnl_pct = (price - pos.entry_price) / pos.entry_price * 100 * self.leverage
        else:
            pnl_pct = (pos.entry_price - price) / pos.entry_price * 100 * self.leverage

        # Always exit on stop loss
        if pnl_pct <= -0.5:  # Stop loss at 0.5%
            return "stop_loss"

        # Take profit - always allowed
        if pnl_pct >= 0.3:  # Take profit at 0.3%
            return "take_profit"

        # Only check flow reversal after minimum hold time
        if hold_seconds >= self.min_hold_seconds:
            if pos.side == 'long' and state.imbalance_pct < -40:
                return "flow_reversal"
            if pos.side == 'short' and state.imbalance_pct > 40:
                return "flow_reversal"

        return None


def run_trading(duration_seconds: int = 300, capital: float = 10, leverage: int = 10):
    """Run paper trading session."""
    trader = HyperliquidTrader(capital=capital, leverage=leverage)
    coins = ['BTC', 'ETH']

    print("=" * 70)
    print("HYPERLIQUID PAPER TRADING - Data-Driven")
    print("=" * 70)
    print(f"Capital: ${capital}")
    print(f"Leverage: {leverage}x")
    print(f"Coins: {coins}")
    print(f"Duration: {duration_seconds}s")
    print(f"Fee: {HL_FEE_PCT}%")
    print(f"Required edge: {REQUIRED_EDGE_PCT}%")
    print("=" * 70)

    start_time = time.time()
    check_count = 0

    try:
        while time.time() - start_time < duration_seconds:
            check_count += 1

            for coin in coins:
                state = trader.get_market_state(coin)
                if not state:
                    continue

                # Status update every 5 checks
                if check_count % 5 == 0:
                    print(f"\n[{coin}] ${state.price:,.2f} | "
                          f"Flow: {state.imbalance_pct:+.1f}% | "
                          f"Funding: {state.funding_rate*100:+.4f}% | "
                          f"Whales: {state.large_trades}")

                # Check for exit
                if trader.position and trader.position.coin == coin:
                    exit_reason = trader.check_exit(state)
                    if exit_reason:
                        trader.close_position(state.price, exit_reason)

                # Check for entry
                if not trader.position:
                    direction, reason = trader.should_trade(state)
                    if direction:
                        trader.open_position(coin, direction, state.price, reason)
                        break  # Only one position at a time

            time.sleep(2)  # Check every 2 seconds

    except KeyboardInterrupt:
        print("\n\nStopped by user.")

    # Close any open position
    if trader.position:
        state = trader.get_market_state(trader.position.coin)
        if state:
            trader.close_position(state.price, "session_end")

    # Summary
    print("\n" + "=" * 70)
    print("SESSION SUMMARY")
    print("=" * 70)
    print(f"Duration: {int(time.time() - start_time)}s")
    print(f"Checks: {check_count}")
    print(f"Trades: {len(trader.trades)}")
    print(f"Total P&L: ${trader.pnl:+.4f}")
    print(f"Final Capital: ${trader.capital:.2f}")
    print(f"Return: {(trader.capital - capital) / capital * 100:+.2f}%")

    if trader.trades:
        winners = sum(1 for t in trader.trades if t.pnl_usd > 0)
        print(f"Win Rate: {winners}/{len(trader.trades)} ({winners/len(trader.trades)*100:.0f}%)")

        print("\n[TRADE LOG]")
        for i, t in enumerate(trader.trades, 1):
            print(f"  {i}. {t.position.side.upper()} {t.position.coin} | "
                  f"${t.position.entry_price:,.2f} -> ${t.exit_price:,.2f} | "
                  f"{t.pnl_pct:+.3f}% | {t.exit_reason}")

    print("=" * 70)


if __name__ == "__main__":
    import sys

    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    capital = float(sys.argv[2]) if len(sys.argv) > 2 else 10
    leverage = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    run_trading(duration, capital, leverage)
