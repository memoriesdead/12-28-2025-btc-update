#!/usr/bin/env python3
"""Quick trade analysis for Hyperliquid."""

import requests
import sys

session = requests.Session()
session.trust_env = False  # Skip proxy

def analyze_trades(coin='BTC'):
    resp = session.post(
        'https://api.hyperliquid.xyz/info',
        json={'type': 'recentTrades', 'coin': coin},
        timeout=10
    )
    trades = resp.json()

    print(f"\n=== {coin} TRADE ANALYSIS ===")
    print(f"Total trades: {len(trades)}")

    buys = [t for t in trades if t['side'] == 'B']
    sells = [t for t in trades if t['side'] == 'A']

    buy_vol = sum(float(t['sz']) * float(t['px']) for t in buys)
    sell_vol = sum(float(t['sz']) * float(t['px']) for t in sells)
    total_vol = buy_vol + sell_vol

    print(f"Buy volume: ${buy_vol:,.0f}")
    print(f"Sell volume: ${sell_vol:,.0f}")
    print(f"Net flow: ${buy_vol - sell_vol:+,.0f}")

    if total_vol > 0:
        imbalance = (buy_vol - sell_vol) / total_vol * 100
        print(f"Imbalance: {imbalance:+.1f}%")

    # Large trades
    large = [t for t in trades if float(t['sz']) * float(t['px']) > 25000]
    print(f"\nLarge trades (>$25k): {len(large)}")

    for t in large[:10]:
        side = 'BUY' if t['side'] == 'B' else 'SELL'
        size_usd = float(t['sz']) * float(t['px'])
        print(f"  {side} ${size_usd:,.0f} @ {float(t['px']):,.2f}")

    # Determine signal
    print(f"\n=== SIGNAL ===")
    if abs(imbalance) > 20:
        direction = 'LONG' if imbalance > 0 else 'SHORT'
        print(f"Direction: {direction}")
        print(f"Reason: Order flow imbalance {imbalance:+.1f}%")
    else:
        print("No signal - flow balanced")


if __name__ == '__main__':
    coins = sys.argv[1:] if len(sys.argv) > 1 else ['BTC', 'ETH']
    for coin in coins:
        analyze_trades(coin)
