#!/usr/bin/env python3
"""
TEST ALL CCXT EXCHANGES - Data Never Lies
==========================================

Comprehensive liquidity analysis across ALL exchanges.
Calculate price impact for various deposit sizes.
Identify which exchanges are tradeable for deterministic strategy.
"""

import ccxt
import time
from datetime import datetime
from typing import List, Tuple, Dict, Optional


def calculate_price_impact(sell_btc: float, bids: List) -> Dict:
    """Calculate exact price impact of a market sell order."""
    if not bids or sell_btc <= 0:
        return {
            'start_price': 0, 'end_price': 0, 'vwap': 0,
            'price_drop_pct': 0, 'volume_filled': 0, 'levels_eaten': 0
        }

    remaining = sell_btc
    start_price = float(bids[0][0])
    end_price = start_price
    levels_eaten = 0
    total_cost = 0.0
    total_filled = 0.0

    for level in bids:
        if remaining <= 0:
            break
        price = float(level[0])
        volume = float(level[1])
        fill = min(remaining, volume)
        total_cost += price * fill
        total_filled += fill
        remaining -= fill
        end_price = price
        levels_eaten += 1

    price_drop_pct = (start_price - end_price) / start_price * 100 if start_price > 0 else 0
    vwap = total_cost / total_filled if total_filled > 0 else start_price

    return {
        'start_price': start_price,
        'end_price': end_price,
        'vwap': vwap,
        'price_drop_pct': price_drop_pct,
        'volume_filled': total_filled,
        'volume_remaining': remaining,
        'levels_eaten': levels_eaten
    }


def test_exchange(exchange_id: str, depth: int = 50) -> Optional[Dict]:
    """Test a single exchange for BTC/USDT or BTC/USD liquidity."""
    try:
        # Initialize exchange
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'enableRateLimit': True,
            'timeout': 10000
        })

        # Find BTC trading pair
        exchange.load_markets()
        symbol = None
        for s in ['BTC/USDT', 'BTC/USD', 'BTC/BUSD', 'BTC/EUR']:
            if s in exchange.symbols:
                symbol = s
                break

        if not symbol:
            return {'exchange': exchange_id, 'error': 'No BTC pair found'}

        # Fetch order book
        book = exchange.fetch_order_book(symbol, limit=depth)
        bids = book.get('bids', [])
        asks = book.get('asks', [])

        if not bids:
            return {'exchange': exchange_id, 'error': 'Empty order book'}

        # Calculate total depth
        total_bid_btc = sum(float(b[1]) for b in bids)
        total_ask_btc = sum(float(a[1]) for a in asks) if asks else 0
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0]) if asks else best_bid
        spread_pct = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0

        # Calculate impact for various deposit sizes
        test_sizes = [1, 5, 10, 25, 50, 100]
        impacts = {}

        for size in test_sizes:
            impact = calculate_price_impact(size, bids)
            impacts[size] = {
                'drop_pct': impact['price_drop_pct'],
                'levels': impact['levels_eaten'],
                'filled': impact['volume_filled'],
                'vwap': impact['vwap']
            }

        # Find minimum tradeable size (impact > 0.2% which is 2x 0.1% fees)
        min_tradeable = None
        for size in test_sizes:
            if impacts[size]['drop_pct'] >= 0.20:
                min_tradeable = size
                break

        return {
            'exchange': exchange_id,
            'symbol': symbol,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread_pct': spread_pct,
            'total_bid_btc': total_bid_btc,
            'total_ask_btc': total_ask_btc,
            'levels': len(bids),
            'impacts': impacts,
            'min_tradeable_btc': min_tradeable,
            'tradeable': min_tradeable is not None and min_tradeable <= 50,
            'error': None
        }

    except ccxt.NetworkError as e:
        return {'exchange': exchange_id, 'error': f'Network: {str(e)[:50]}'}
    except ccxt.ExchangeError as e:
        return {'exchange': exchange_id, 'error': f'Exchange: {str(e)[:50]}'}
    except Exception as e:
        return {'exchange': exchange_id, 'error': f'{type(e).__name__}: {str(e)[:50]}'}


def main():
    print("=" * 80)
    print("CCXT EXCHANGE LIQUIDITY ANALYSIS - DATA NEVER LIES")
    print("=" * 80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Get all CCXT exchanges
    all_exchanges = ccxt.exchanges
    print(f"Total CCXT exchanges: {len(all_exchanges)}")
    print()

    # Major exchanges to test first (most likely to work)
    priority_exchanges = [
        'binance', 'binanceus', 'coinbase', 'kraken', 'bitstamp',
        'gemini', 'bitfinex', 'okx', 'bybit', 'kucoin',
        'huobi', 'gateio', 'mexc', 'bitget', 'cryptocom',
        'poloniex', 'bitmex', 'deribit', 'phemex', 'htx'
    ]

    # Other exchanges
    other_exchanges = [e for e in all_exchanges if e not in priority_exchanges]

    results = []
    tradeable = []
    errors = []

    print("Testing PRIORITY exchanges (20)...")
    print("-" * 80)

    for i, exchange_id in enumerate(priority_exchanges):
        print(f"[{i+1}/{len(priority_exchanges)}] Testing {exchange_id}...", end=" ", flush=True)
        result = test_exchange(exchange_id)
        results.append(result)

        if result.get('error'):
            print(f"ERROR: {result['error']}")
            errors.append(result)
        else:
            print(f"OK - {result['total_bid_btc']:.2f} BTC depth, " +
                  f"1 BTC = {result['impacts'][1]['drop_pct']:.4f}% impact")
            if result['tradeable']:
                tradeable.append(result)

        time.sleep(0.5)  # Rate limiting

    print()
    print("Testing OTHER exchanges (sampling 30 more)...")
    print("-" * 80)

    # Sample other exchanges
    import random
    sampled_others = random.sample(other_exchanges, min(30, len(other_exchanges)))

    for i, exchange_id in enumerate(sampled_others):
        print(f"[{i+1}/{len(sampled_others)}] Testing {exchange_id}...", end=" ", flush=True)
        result = test_exchange(exchange_id)
        results.append(result)

        if result.get('error'):
            print(f"ERROR: {result['error']}")
            errors.append(result)
        else:
            print(f"OK - {result['total_bid_btc']:.2f} BTC depth, " +
                  f"1 BTC = {result['impacts'][1]['drop_pct']:.4f}% impact")
            if result['tradeable']:
                tradeable.append(result)

        time.sleep(0.5)

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY - DATA NEVER LIES")
    print("=" * 80)
    print()

    print(f"Exchanges tested: {len(results)}")
    print(f"Successful: {len(results) - len(errors)}")
    print(f"Errors: {len(errors)}")
    print(f"TRADEABLE (impact > 0.2% with <= 50 BTC): {len(tradeable)}")
    print()

    if tradeable:
        print("TRADEABLE EXCHANGES (sorted by liquidity - thinnest first):")
        print("-" * 80)

        # Sort by total depth (ascending - thinner = better for our strategy)
        tradeable.sort(key=lambda x: x['total_bid_btc'])

        for r in tradeable:
            print(f"\n{r['exchange'].upper()} ({r['symbol']})")
            print(f"  Best Bid: ${r['best_bid']:,.2f}")
            print(f"  Spread: {r['spread_pct']:.4f}%")
            print(f"  Total Depth: {r['total_bid_btc']:.2f} BTC ({r['levels']} levels)")
            print(f"  Min Tradeable: {r['min_tradeable_btc']} BTC")
            print(f"  Impact Table:")
            for size, imp in r['impacts'].items():
                status = ">>> TRADE" if imp['drop_pct'] >= 0.20 else "    skip"
                print(f"    {size:3d} BTC: {imp['drop_pct']:6.4f}% drop, VWAP ${imp['vwap']:,.2f} {status}")

    print()
    print("=" * 80)
    print("LIQUID EXCHANGES (for reference - NOT tradeable with our strategy):")
    print("-" * 80)

    liquid = [r for r in results if not r.get('error') and not r.get('tradeable')]
    liquid.sort(key=lambda x: x['total_bid_btc'], reverse=True)

    for r in liquid[:10]:  # Top 10 most liquid
        print(f"{r['exchange']:15s} | Depth: {r['total_bid_btc']:10.2f} BTC | " +
              f"1 BTC impact: {r['impacts'][1]['drop_pct']:.6f}%")

    print()
    print("=" * 80)
    print("DETERMINISTIC TRADING CONCLUSION")
    print("=" * 80)
    print()
    print("For 100% win rate deterministic trading:")
    print("  - We need: impact > 2x fees (> 0.20% for 0.10% fees)")
    print("  - Best targets: THIN order books where our signal size moves price")
    print()
    if tradeable:
        best = tradeable[0]
        print(f"BEST EXCHANGE: {best['exchange'].upper()}")
        print(f"  - Only {best['total_bid_btc']:.2f} BTC total depth")
        print(f"  - {best['min_tradeable_btc']} BTC deposit causes {best['impacts'][best['min_tradeable_btc']]['drop_pct']:.4f}% impact")
        print(f"  - With 125x leverage: {best['impacts'][best['min_tradeable_btc']]['drop_pct'] * 125:.2f}% return")
    else:
        print("No exchanges found with thin enough liquidity for deterministic trading.")
        print("Consider: smaller/regional exchanges, specific trading pairs, or wait for low-liquidity periods.")
    print()
    print("DATA NEVER LIES. MATH NEVER LIES.")
    print("=" * 80)


if __name__ == "__main__":
    main()
