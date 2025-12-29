#!/usr/bin/env python3
"""
MULTI-EXCHANGE PRICE FEED
=========================
Track price separately for each exchange.

Supported exchanges:
- Binance, Coinbase, Kraken, Bitfinex, OKX, Bybit
- Huobi/HTX, Bitstamp, KuCoin, Gate.io, Gemini, Crypto.com
"""

import time
import threading
import requests
from datetime import datetime
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass


@dataclass
class ExchangePrice:
    """Price data from an exchange."""
    exchange: str
    price: float
    timestamp: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: Optional[float] = None


class MultiExchangePriceFeed:
    """Fetch BTC/USD(T) prices from multiple exchanges."""

    def __init__(self, refresh_interval: float = 1.0):
        self.refresh_interval = refresh_interval
        self.prices: Dict[str, ExchangePrice] = {}
        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.callbacks: List[Callable[[str, float], None]] = []
        self.last_fetch: Dict[str, float] = {}

    def add_callback(self, callback: Callable[[str, float], None]):
        """Add callback for price updates. callback(exchange, price)"""
        self.callbacks.append(callback)

    def _fetch_binance(self) -> Optional[ExchangePrice]:
        """Fetch from Binance - tries Binance.US first, then global, then CoinGecko."""
        try:
            r = requests.get('https://api.binance.us/api/v3/ticker/bookTicker?symbol=BTCUSD', timeout=5)
            if r.status_code == 200:
                data = r.json()
                bid, ask = float(data['bidPrice']), float(data['askPrice'])
                return ExchangePrice(exchange='binance', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        try:
            r = requests.get('https://api.binance.com/api/v3/ticker/bookTicker?symbol=BTCUSDT', timeout=5)
            if r.status_code == 200:
                data = r.json()
                bid, ask = float(data['bidPrice']), float(data['askPrice'])
                return ExchangePrice(exchange='binance', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        try:
            r = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd', timeout=5)
            if r.status_code == 200:
                return ExchangePrice(exchange='binance', price=float(r.json()['bitcoin']['usd']), timestamp=time.time())
        except Exception:
            pass
        return None

    def _fetch_coinbase(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api.coinbase.com/v2/prices/BTC-USD/spot', timeout=5)
            if r.status_code == 200:
                return ExchangePrice(exchange='coinbase', price=float(r.json()['data']['amount']), timestamp=time.time())
        except Exception:
            pass
        return None

    def _fetch_kraken(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api.kraken.com/0/public/Ticker?pair=XBTUSD', timeout=5)
            if r.status_code == 200:
                ticker = r.json()['result']['XXBTZUSD']
                bid, ask = float(ticker['b'][0]), float(ticker['a'][0])
                return ExchangePrice(exchange='kraken', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_bitfinex(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api-pub.bitfinex.com/v2/ticker/tBTCUSD', timeout=5)
            if r.status_code == 200:
                data = r.json()
                bid, ask = float(data[0]), float(data[2])
                return ExchangePrice(exchange='bitfinex', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_okx(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT', timeout=5)
            if r.status_code == 200:
                ticker = r.json()['data'][0]
                bid, ask = float(ticker['bidPx']), float(ticker['askPx'])
                return ExchangePrice(exchange='okx', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_bybit(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT', timeout=5)
            if r.status_code == 200:
                ticker = r.json()['result']['list'][0]
                bid, ask = float(ticker['bid1Price']), float(ticker['ask1Price'])
                return ExchangePrice(exchange='bybit', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_huobi(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api.huobi.pro/market/detail/merged?symbol=btcusdt', timeout=5)
            if r.status_code == 200:
                tick = r.json()['tick']
                bid, ask = float(tick['bid'][0]), float(tick['ask'][0])
                return ExchangePrice(exchange='huobi', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_bitstamp(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://www.bitstamp.net/api/v2/ticker/btcusd/', timeout=5)
            if r.status_code == 200:
                data = r.json()
                bid, ask = float(data['bid']), float(data['ask'])
                return ExchangePrice(exchange='bitstamp', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_kucoin(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=BTC-USDT', timeout=5)
            if r.status_code == 200:
                ticker = r.json()['data']
                bid, ask = float(ticker['bestBid']), float(ticker['bestAsk'])
                return ExchangePrice(exchange='kucoin', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_gateio(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BTC_USDT', timeout=5)
            if r.status_code == 200:
                ticker = r.json()[0]
                bid, ask = float(ticker['highest_bid']), float(ticker['lowest_ask'])
                return ExchangePrice(exchange='gate.io', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_gemini(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api.gemini.com/v1/pubticker/btcusd', timeout=5)
            if r.status_code == 200:
                data = r.json()
                bid, ask = float(data['bid']), float(data['ask'])
                return ExchangePrice(exchange='gemini', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    def _fetch_cryptocom(self) -> Optional[ExchangePrice]:
        try:
            r = requests.get('https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT', timeout=5)
            if r.status_code == 200:
                ticker = r.json()['result']['data']
                bid, ask = float(ticker['b']), float(ticker['k'])
                return ExchangePrice(exchange='crypto.com', price=(bid + ask) / 2, timestamp=time.time(), bid=bid, ask=ask)
        except Exception:
            pass
        return None

    FETCHERS = {
        'binance': '_fetch_binance', 'coinbase': '_fetch_coinbase', 'kraken': '_fetch_kraken',
        'bitfinex': '_fetch_bitfinex', 'okx': '_fetch_okx', 'bybit': '_fetch_bybit',
        'huobi': '_fetch_huobi', 'bitstamp': '_fetch_bitstamp', 'kucoin': '_fetch_kucoin',
        'gate.io': '_fetch_gateio', 'gemini': '_fetch_gemini', 'crypto.com': '_fetch_cryptocom',
    }

    def fetch_price(self, exchange: str) -> Optional[float]:
        """Fetch current price from a specific exchange."""
        if exchange not in self.FETCHERS:
            return None
        fetcher = getattr(self, self.FETCHERS[exchange])
        result = fetcher()
        if result:
            with self.lock:
                self.prices[exchange] = result
                self.last_fetch[exchange] = time.time()
            for cb in self.callbacks:
                try:
                    cb(exchange, result.price)
                except Exception:
                    pass
            return result.price
        return None

    def fetch_all(self) -> Dict[str, float]:
        """Fetch prices from all exchanges."""
        prices = {}
        for exchange in self.FETCHERS:
            price = self.fetch_price(exchange)
            if price:
                prices[exchange] = price
        return prices

    def get_price(self, exchange: str, max_age: float = 5.0) -> Optional[float]:
        """Get cached price for an exchange."""
        with self.lock:
            if exchange in self.prices:
                age = time.time() - self.prices[exchange].timestamp
                if age <= max_age:
                    return self.prices[exchange].price
        return self.fetch_price(exchange)

    def get_all_prices(self) -> Dict[str, ExchangePrice]:
        """Get all cached prices."""
        with self.lock:
            return dict(self.prices)

    def _run_loop(self):
        """Background thread to refresh prices."""
        while self.running:
            try:
                self.fetch_all()
            except Exception:
                pass
            time.sleep(self.refresh_interval)

    def start(self):
        """Start background price updates."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f"[PRICE] Started multi-exchange price feed ({len(self.FETCHERS)} exchanges)")

    def stop(self):
        """Stop background updates."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)


def get_exchange_price(exchange: str) -> Optional[float]:
    """Convenience function to get a single exchange price."""
    feed = MultiExchangePriceFeed()
    return feed.fetch_price(exchange)


if __name__ == '__main__':
    print("=" * 70)
    print("MULTI-EXCHANGE PRICE FEED TEST")
    print("=" * 70)
    feed = MultiExchangePriceFeed()
    prices = feed.fetch_all()
    print(f"\n{'Exchange':<15} {'Price':>12} {'Bid':>12} {'Ask':>12}")
    print("-" * 55)
    for exchange, price in sorted(prices.items(), key=lambda x: -x[1]):
        p = feed.prices[exchange]
        bid_str = f"${p.bid:,.2f}" if p.bid else "-"
        ask_str = f"${p.ask:,.2f}" if p.ask else "-"
        print(f"{exchange:<15} ${price:>11,.2f} {bid_str:>12} {ask_str:>12}")
    print(f"\nSuccessfully fetched {len(prices)} exchange prices")
