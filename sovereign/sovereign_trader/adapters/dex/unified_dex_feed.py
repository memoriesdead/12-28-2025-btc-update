#!/usr/bin/env python3
"""
Unified DEX Data Feed - Deterministic Approach
===============================================

Cross-reference data from all DEX nodes + CCXT.
Let the data speak. Follow the math.

Sources:
1. Hyperliquid (node + API)
2. dYdX (CCXT + node when running)
3. Paradex (CCXT)
4. Apex (CCXT)

Strategy:
- Get orderbook + trades from each DEX
- Calculate order flow imbalance
- Find arbitrage between DEXes
- Trade where math works (impact > 2×fees)
"""

import requests
import time
import ccxt
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Fee structure for each DEX
DEX_FEES = {
    'hyperliquid': 0.035,  # 0.035%
    'dydx': 0.050,         # 0.05%
    'paradex': 0.040,      # 0.04%
    'apex': 0.050,         # 0.05%
}


@dataclass
class DEXState:
    """Current state of a DEX."""
    name: str
    price: float
    bid: float
    ask: float
    spread_pct: float
    buy_volume: float
    sell_volume: float
    imbalance_pct: float
    funding_rate: float
    timestamp: datetime


@dataclass
class ArbitrageOpportunity:
    """Cross-DEX arbitrage opportunity."""
    buy_dex: str
    sell_dex: str
    buy_price: float
    sell_price: float
    spread_pct: float
    net_profit_pct: float  # After fees
    size_available: float


class UnifiedDEXFeed:
    """Unified data feed from all DEX sources."""

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False  # Skip VPS proxy

        # Initialize CCXT exchanges
        self.exchanges = {}
        self._init_ccxt()

    def _init_ccxt(self):
        """Initialize CCXT exchange connections."""
        try:
            self.exchanges['dydx'] = ccxt.dydx({
                'enableRateLimit': True,
            })
        except Exception as e:
            print(f"[WARN] dYdX CCXT init failed: {e}")

        try:
            self.exchanges['hyperliquid'] = ccxt.hyperliquid({
                'enableRateLimit': True,
            })
        except Exception as e:
            print(f"[WARN] Hyperliquid CCXT init failed: {e}")

        try:
            self.exchanges['paradex'] = ccxt.paradex({
                'enableRateLimit': True,
            })
        except Exception as e:
            print(f"[WARN] Paradex CCXT init failed: {e}")

        try:
            self.exchanges['apex'] = ccxt.apex({
                'enableRateLimit': True,
            })
        except Exception as e:
            print(f"[WARN] Apex CCXT init failed: {e}")

    def get_hyperliquid_state(self, coin: str = 'BTC') -> Optional[DEXState]:
        """Get Hyperliquid state via direct API (faster than CCXT)."""
        try:
            # Get orderbook
            resp = self.session.post(
                'https://api.hyperliquid.xyz/info',
                json={'type': 'l2Book', 'coin': coin},
                timeout=5
            )
            book = resp.json()

            levels = book.get('levels', [[], []])
            bids = levels[0] if levels else []
            asks = levels[1] if len(levels) > 1 else []

            bid = float(bids[0]['px']) if bids else 0
            ask = float(asks[0]['px']) if asks else 0
            spread = (ask - bid) / bid * 100 if bid > 0 else 0

            # Get recent trades for flow
            resp2 = self.session.post(
                'https://api.hyperliquid.xyz/info',
                json={'type': 'recentTrades', 'coin': coin},
                timeout=5
            )
            trades = resp2.json()

            buy_vol = sum(float(t['sz']) * float(t['px']) for t in trades if t['side'] == 'B')
            sell_vol = sum(float(t['sz']) * float(t['px']) for t in trades if t['side'] == 'A')
            total = buy_vol + sell_vol
            imbalance = (buy_vol - sell_vol) / total * 100 if total > 0 else 0

            # Get funding
            resp3 = self.session.post(
                'https://api.hyperliquid.xyz/info',
                json={'type': 'metaAndAssetCtxs'},
                timeout=5
            )
            meta = resp3.json()
            funding = 0
            for i, asset in enumerate(meta[0]['universe']):
                if asset['name'] == coin:
                    funding = float(meta[1][i].get('funding', 0))
                    break

            return DEXState(
                name='hyperliquid',
                price=(bid + ask) / 2,
                bid=bid,
                ask=ask,
                spread_pct=spread,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                imbalance_pct=imbalance,
                funding_rate=funding,
                timestamp=datetime.now()
            )

        except Exception as e:
            print(f"[ERROR] Hyperliquid: {e}")
            return None

    def get_ccxt_state(self, exchange_name: str, symbol: str = 'BTC/USD:USD') -> Optional[DEXState]:
        """Get state from CCXT exchange."""
        try:
            exchange = self.exchanges.get(exchange_name)
            if not exchange:
                return None

            # Get orderbook
            book = exchange.fetch_order_book(symbol, limit=20)
            bid = book['bids'][0][0] if book['bids'] else 0
            ask = book['asks'][0][0] if book['asks'] else 0
            spread = (ask - bid) / bid * 100 if bid > 0 else 0

            # Get recent trades
            trades = exchange.fetch_trades(symbol, limit=50)
            buy_vol = sum(t['amount'] * t['price'] for t in trades if t['side'] == 'buy')
            sell_vol = sum(t['amount'] * t['price'] for t in trades if t['side'] == 'sell')
            total = buy_vol + sell_vol
            imbalance = (buy_vol - sell_vol) / total * 100 if total > 0 else 0

            return DEXState(
                name=exchange_name,
                price=(bid + ask) / 2,
                bid=bid,
                ask=ask,
                spread_pct=spread,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                imbalance_pct=imbalance,
                funding_rate=0,  # Would need separate call
                timestamp=datetime.now()
            )

        except Exception as e:
            print(f"[ERROR] {exchange_name}: {e}")
            return None

    def get_all_states(self, coin: str = 'BTC') -> Dict[str, DEXState]:
        """Get state from all DEXes in parallel."""
        states = {}

        # Symbol mapping per DEX
        symbols = {
            'dydx': f'{coin}/USDC:USDC',
            'paradex': f'{coin}/USDC',
            'apex': f'{coin}/USDT:USDT',
        }

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self.get_hyperliquid_state, coin): 'hyperliquid',
                executor.submit(self.get_ccxt_state, 'dydx', symbols['dydx']): 'dydx',
            }

            for future in as_completed(futures, timeout=10):
                name = futures[future]
                try:
                    state = future.result()
                    if state:
                        states[name] = state
                except Exception as e:
                    print(f"[ERROR] {name}: {e}")

        return states

    def find_arbitrage(self, states: Dict[str, DEXState]) -> List[ArbitrageOpportunity]:
        """Find arbitrage opportunities between DEXes."""
        opportunities = []

        dexes = list(states.keys())
        for i, dex1 in enumerate(dexes):
            for dex2 in dexes[i+1:]:
                state1 = states[dex1]
                state2 = states[dex2]

                # Check if we can buy on dex1 and sell on dex2
                if state1.ask < state2.bid:
                    spread = (state2.bid - state1.ask) / state1.ask * 100
                    fees = DEX_FEES.get(dex1, 0.05) + DEX_FEES.get(dex2, 0.05)
                    net_profit = spread - fees

                    if net_profit > 0:
                        opportunities.append(ArbitrageOpportunity(
                            buy_dex=dex1,
                            sell_dex=dex2,
                            buy_price=state1.ask,
                            sell_price=state2.bid,
                            spread_pct=spread,
                            net_profit_pct=net_profit,
                            size_available=0  # Would calculate from orderbook depth
                        ))

                # Check reverse direction
                if state2.ask < state1.bid:
                    spread = (state1.bid - state2.ask) / state2.ask * 100
                    fees = DEX_FEES.get(dex1, 0.05) + DEX_FEES.get(dex2, 0.05)
                    net_profit = spread - fees

                    if net_profit > 0:
                        opportunities.append(ArbitrageOpportunity(
                            buy_dex=dex2,
                            sell_dex=dex1,
                            buy_price=state2.ask,
                            sell_price=state1.bid,
                            spread_pct=spread,
                            net_profit_pct=net_profit,
                            size_available=0
                        ))

        return opportunities

    def analyze_flow_consensus(self, states: Dict[str, DEXState]) -> Tuple[str, float]:
        """
        Analyze order flow consensus across DEXes.
        Returns direction and confidence.
        """
        if not states:
            return None, 0

        # Weight by volume
        total_buy = sum(s.buy_volume for s in states.values())
        total_sell = sum(s.sell_volume for s in states.values())
        total = total_buy + total_sell

        if total == 0:
            return None, 0

        consensus_imbalance = (total_buy - total_sell) / total * 100

        # Count how many DEXes agree on direction
        agreeing = 0
        for state in states.values():
            if consensus_imbalance > 0 and state.imbalance_pct > 0:
                agreeing += 1
            elif consensus_imbalance < 0 and state.imbalance_pct < 0:
                agreeing += 1

        confidence = agreeing / len(states)

        if abs(consensus_imbalance) > 50 and confidence > 0.6:
            direction = 'long' if consensus_imbalance > 0 else 'short'
            return direction, confidence

        return None, 0


def print_market_overview():
    """Print market overview from all DEXes."""
    feed = UnifiedDEXFeed()

    print("=" * 80)
    print("UNIFIED DEX MARKET OVERVIEW")
    print("=" * 80)

    states = feed.get_all_states('BTC')

    if not states:
        print("[ERROR] No data from any DEX")
        return

    print("\n[DEX STATES]")
    print(f"{'DEX':<15} {'Price':<12} {'Spread':<10} {'Flow':<12} {'Funding':<10}")
    print("-" * 60)

    for name, state in states.items():
        print(f"{name:<15} ${state.price:,.2f}  {state.spread_pct:.4f}%   "
              f"{state.imbalance_pct:+.1f}%    {state.funding_rate*100:+.4f}%")

    # Check for arbitrage
    arbs = feed.find_arbitrage(states)
    if arbs:
        print("\n[ARBITRAGE OPPORTUNITIES]")
        for arb in arbs:
            print(f"  BUY {arb.buy_dex} @ ${arb.buy_price:,.2f} -> "
                  f"SELL {arb.sell_dex} @ ${arb.sell_price:,.2f} = "
                  f"{arb.net_profit_pct:+.3f}% profit")
    else:
        print("\n[ARBITRAGE] No opportunities found")

    # Check flow consensus
    direction, confidence = feed.analyze_flow_consensus(states)
    print("\n[FLOW CONSENSUS]")
    if direction:
        print(f"  Direction: {direction.upper()}")
        print(f"  Confidence: {confidence:.0%}")
    else:
        print("  No consensus - flows diverge")

    print("=" * 80)


def run_monitor(duration_seconds: int = 300):
    """Run continuous monitor."""
    feed = UnifiedDEXFeed()

    print("=" * 80)
    print("UNIFIED DEX MONITOR")
    print("=" * 80)
    print(f"Duration: {duration_seconds}s")
    print("=" * 80)

    start = time.time()
    while time.time() - start < duration_seconds:
        states = feed.get_all_states('BTC')

        # Print compact status
        prices = " | ".join(f"{n}: ${s.price:,.0f}" for n, s in states.items())
        flows = " | ".join(f"{n}: {s.imbalance_pct:+.0f}%" for n, s in states.items())
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
        print(f"  Prices: {prices}")
        print(f"  Flows:  {flows}")

        # Check arbitrage
        arbs = feed.find_arbitrage(states)
        if arbs:
            for arb in arbs:
                print(f"  [ARB] {arb.buy_dex} -> {arb.sell_dex}: {arb.net_profit_pct:+.3f}%")

        # Check consensus
        direction, confidence = feed.analyze_flow_consensus(states)
        if direction:
            print(f"  [SIGNAL] {direction.upper()} ({confidence:.0%} confidence)")

        time.sleep(5)

    print("\n" + "=" * 80)
    print("Monitor ended")
    print("=" * 80)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "monitor":
        duration = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        run_monitor(duration)
    else:
        print_market_overview()
