"""
LAYER 3: CCXT Data Pipeline - Real-time market confirmation for ALL 7 INSTRUMENTS

This is the final confirmation layer before trade execution.
Uses REAL market data: recent trades, funding rates, open interest.

Instrument Types and their CCXT data requirements:
  SPOT:            Recent trades only
  MARGIN:          Recent trades + borrow rate
  PERPETUAL:       Recent trades + funding rate + open interest
  FUTURES:         Recent trades + open interest + basis
  OPTIONS:         Recent trades + open interest + IV + delta
  INVERSE:         Recent trades + funding rate + open interest
  LEVERAGED_TOKEN: Recent trades (3x multiplier)
"""
import ccxt
from dataclasses import dataclass
from typing import Optional, Dict
from enum import Enum
import os
import time


class InstrumentType(Enum):
    SPOT = "spot"
    MARGIN = "margin"
    PERPETUAL = "perpetual"
    FUTURES = "futures"
    OPTIONS = "options"
    INVERSE = "inverse"
    LEVERAGED_TOKEN = "leveraged_token"


@dataclass
class MarketConfirmation:
    """All CCXT data for trade confirmation."""
    instrument: InstrumentType
    symbol: str
    exchange: str

    # Recent Trades (ALL instruments)
    recent_sell_volume: float
    recent_buy_volume: float
    trade_direction_bias: float  # -1 (all sells) to +1 (all buys)

    # Funding Rate (PERPETUAL, INVERSE only)
    funding_rate: Optional[float] = None
    funding_bias: str = "NEUTRAL"  # "SHORT", "LONG", or "NEUTRAL"

    # Open Interest (PERPETUAL, FUTURES, INVERSE, OPTIONS)
    open_interest: float = 0.0
    open_interest_change_pct: float = 0.0

    # Margin-specific (MARGIN only)
    borrow_rate: Optional[float] = None

    # Options-specific (OPTIONS only)
    implied_volatility: Optional[float] = None
    delta: Optional[float] = None

    # Fetch status
    fetch_success: bool = True
    fetch_error: Optional[str] = None

    def confirms_short(self) -> bool:
        """Does ALL data confirm SHORT for this instrument?"""
        # Trade direction must show selling (negative bias)
        if self.trade_direction_bias >= 0:
            return False

        # Instrument-specific checks
        if self.instrument in [InstrumentType.PERPETUAL, InstrumentType.INVERSE]:
            # Funding must favor shorts (positive = longs pay shorts)
            if self.funding_rate is not None and self.funding_rate < 0:
                return False

        if self.instrument in [InstrumentType.PERPETUAL, InstrumentType.FUTURES,
                               InstrumentType.INVERSE, InstrumentType.OPTIONS]:
            # OI increasing = new positions = momentum continuing
            if self.open_interest_change_pct < -5:  # Allow small decreases
                return False

        return True

    def confirms_long(self) -> bool:
        """Does ALL data confirm LONG for this instrument?"""
        # Trade direction must show buying (positive bias)
        if self.trade_direction_bias <= 0:
            return False

        # Instrument-specific checks
        if self.instrument in [InstrumentType.PERPETUAL, InstrumentType.INVERSE]:
            # Funding must favor longs (negative = shorts pay longs)
            if self.funding_rate is not None and self.funding_rate > 0:
                return False

        if self.instrument in [InstrumentType.PERPETUAL, InstrumentType.FUTURES,
                               InstrumentType.INVERSE, InstrumentType.OPTIONS]:
            # OI decreasing = positions closing = reversal momentum
            if self.open_interest_change_pct > 5:  # Allow small increases
                return False

        return True

    def strength(self) -> float:
        """Return confirmation strength from 0.0 to 1.0."""
        score = 0.0

        # Trade direction contributes 40%
        score += abs(self.trade_direction_bias) * 0.4

        # Funding alignment contributes 30% (for perps/inverse)
        if self.funding_rate is not None:
            if (self.trade_direction_bias < 0 and self.funding_rate > 0) or \
               (self.trade_direction_bias > 0 and self.funding_rate < 0):
                score += 0.3
            else:
                score -= 0.15

        # OI momentum contributes 30%
        if self.open_interest_change_pct != 0:
            # Positive OI change = momentum
            score += min(0.3, abs(self.open_interest_change_pct) / 10 * 0.3)

        return max(0.0, min(1.0, score))


# Symbol mapping per instrument type for major exchanges
INSTRUMENT_SYMBOLS = {
    InstrumentType.SPOT: {
        'default': 'BTC/USDT',
        'coinbase': 'BTC/USD',
        'kraken': 'BTC/USD',
        'gemini': 'BTC/USD',
        'bitstamp': 'BTC/USD',
    },
    InstrumentType.MARGIN: {
        'default': 'BTC/USDT',
    },
    InstrumentType.PERPETUAL: {
        'default': 'BTC/USDT:USDT',
        'deribit': 'BTC/USD:BTC',
        'bybit': 'BTCUSDT',
        'bitmex': 'XBTUSD',
    },
    InstrumentType.FUTURES: {
        'default': 'BTC/USDT:USDT-250328',  # Quarterly
        'deribit': 'BTC-28MAR25',
        'bitmex': 'XBTM25',
    },
    InstrumentType.OPTIONS: {
        'default': 'BTC/USDT:USDT-250328-100000-C',
        'deribit': 'BTC-28MAR25-100000-C',
    },
    InstrumentType.INVERSE: {
        'default': 'BTC/USD:BTC',
        'bybit': 'BTCUSD',
        'bitmex': 'XBTUSD',
    },
    InstrumentType.LEVERAGED_TOKEN: {
        'default': 'BTC3L/USDT',
        'binance': 'BTCUP/USDT',
        'gate': 'BTC3L/USDT',
    },
}


class CCXTDataPipeline:
    """Fetch real-time market data for ALL 7 instrument types."""

    def __init__(self):
        self.proxy = os.environ.get('HTTPS_PROXY', 'http://141.147.58.130:8888')
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.last_open_interest: Dict[str, float] = {}
        self._init_exchanges()

    def _init_exchanges(self):
        """Initialize exchange connections."""
        # Exchanges that support various instruments
        exchange_classes = {
            'okx': ccxt.okx,        # All 7 instruments
            'binance': ccxt.binance,  # SPOT, MARGIN, PERP, FUTURES
            'bybit': ccxt.bybit,    # SPOT, PERP, INVERSE
            'gate': ccxt.gate,      # All 7 instruments
            'deribit': ccxt.deribit,  # PERP, FUTURES, OPTIONS, INVERSE
            'htx': ccxt.htx,        # SPOT, MARGIN, PERP, FUTURES, INVERSE
            'bitget': ccxt.bitget,  # SPOT, MARGIN, PERP, FUTURES
            'kucoin': ccxt.kucoin,  # SPOT, MARGIN
            'mexc': ccxt.mexc,      # SPOT, MARGIN, PERP, FUTURES
            'phemex': ccxt.phemex,  # SPOT, PERP, FUTURES, INVERSE
            'coinex': ccxt.coinex,  # SPOT, MARGIN, PERP, FUTURES
            'bitfinex': ccxt.bitfinex,  # SPOT, MARGIN, PERP
            'poloniex': ccxt.poloniex,  # SPOT, MARGIN, PERP
            'kraken': ccxt.kraken,  # SPOT, MARGIN (no proxy needed)
            'coinbase': ccxt.coinbase,  # SPOT (no proxy needed)
            'gemini': ccxt.gemini,  # SPOT (no proxy needed)
        }

        # US exchanges don't need proxy
        us_exchanges = {'kraken', 'coinbase', 'gemini', 'bitstamp'}

        for name, cls in exchange_classes.items():
            try:
                config = {'enableRateLimit': True}
                if name not in us_exchanges:
                    config['proxies'] = {'https': self.proxy, 'http': self.proxy}

                self.exchanges[name] = cls(config)
            except Exception as e:
                print(f"[CCXT] Failed to init {name}: {e}")

    def get_symbol(self, instrument: InstrumentType, exchange: str) -> str:
        """Get correct symbol for instrument type on specific exchange."""
        symbols = INSTRUMENT_SYMBOLS.get(instrument, {})
        return symbols.get(exchange.lower(), symbols.get('default', 'BTC/USDT'))

    def get_confirmation(self, exchange: str, instrument: InstrumentType) -> MarketConfirmation:
        """Get full market confirmation for specific instrument."""
        ex = self.exchanges.get(exchange.lower())
        symbol = self.get_symbol(instrument, exchange)

        result = MarketConfirmation(
            instrument=instrument,
            symbol=symbol,
            exchange=exchange,
            recent_sell_volume=0.0,
            recent_buy_volume=0.0,
            trade_direction_bias=0.0,
        )

        if not ex:
            result.fetch_success = False
            result.fetch_error = f"Exchange {exchange} not initialized"
            return result

        try:
            # ============================================
            # RECENT TRADES (ALL instruments)
            # ============================================
            sell_vol, buy_vol = self._fetch_trades(ex, symbol)
            result.recent_sell_volume = sell_vol
            result.recent_buy_volume = buy_vol

            total_vol = sell_vol + buy_vol
            if total_vol > 0:
                result.trade_direction_bias = (buy_vol - sell_vol) / total_vol
            # bias: -1 = all sells, +1 = all buys

            # ============================================
            # FUNDING RATE (PERPETUAL, INVERSE only)
            # ============================================
            if instrument in [InstrumentType.PERPETUAL, InstrumentType.INVERSE]:
                funding = self._fetch_funding_rate(ex, symbol)
                if funding is not None:
                    result.funding_rate = funding
                    # Positive funding = longs pay shorts = SHORT bias
                    # Negative funding = shorts pay longs = LONG bias
                    if funding > 0.0001:  # > 0.01%
                        result.funding_bias = "SHORT"
                    elif funding < -0.0001:
                        result.funding_bias = "LONG"
                    else:
                        result.funding_bias = "NEUTRAL"

            # ============================================
            # OPEN INTEREST (PERPETUAL, FUTURES, INVERSE, OPTIONS)
            # ============================================
            if instrument in [InstrumentType.PERPETUAL, InstrumentType.FUTURES,
                              InstrumentType.INVERSE, InstrumentType.OPTIONS]:
                oi, oi_change = self._fetch_open_interest(ex, symbol, exchange, instrument)
                result.open_interest = oi
                result.open_interest_change_pct = oi_change

            # ============================================
            # BORROW RATE (MARGIN only)
            # ============================================
            if instrument == InstrumentType.MARGIN:
                borrow = self._fetch_borrow_rate(ex)
                result.borrow_rate = borrow

        except Exception as e:
            result.fetch_success = False
            result.fetch_error = str(e)

        return result

    def _fetch_trades(self, ex: ccxt.Exchange, symbol: str) -> tuple:
        """Fetch recent trades and calculate buy/sell volume."""
        try:
            trades = ex.fetch_trades(symbol, limit=100)
            sell_vol = sum(t['amount'] for t in trades if t.get('side') == 'sell')
            buy_vol = sum(t['amount'] for t in trades if t.get('side') == 'buy')
            return sell_vol, buy_vol
        except Exception:
            return 0.0, 0.0

    def _fetch_funding_rate(self, ex: ccxt.Exchange, symbol: str) -> Optional[float]:
        """Fetch current funding rate."""
        try:
            if hasattr(ex, 'fetch_funding_rate'):
                data = ex.fetch_funding_rate(symbol)
                return data.get('fundingRate')
        except Exception:
            pass
        return None

    def _fetch_open_interest(self, ex: ccxt.Exchange, symbol: str,
                             exchange: str, instrument: InstrumentType) -> tuple:
        """Fetch open interest and calculate change."""
        try:
            if hasattr(ex, 'fetch_open_interest'):
                data = ex.fetch_open_interest(symbol)
                current = data.get('openInterestAmount', 0) or data.get('openInterest', 0)

                # Track change from last fetch
                key = f"{exchange}:{instrument.value}"
                last = self.last_open_interest.get(key, current)
                change_pct = ((current - last) / last * 100) if last > 0 else 0
                self.last_open_interest[key] = current

                return float(current), change_pct
        except Exception:
            pass
        return 0.0, 0.0

    def _fetch_borrow_rate(self, ex: ccxt.Exchange) -> Optional[float]:
        """Fetch BTC borrow rate for margin trading."""
        try:
            if hasattr(ex, 'fetch_borrow_rate'):
                data = ex.fetch_borrow_rate('BTC')
                return data.get('rate')
        except Exception:
            pass
        return None

    def get_all_confirmations(self, exchanges: list, instrument: InstrumentType) -> Dict[str, MarketConfirmation]:
        """Get confirmations from multiple exchanges."""
        results = {}
        for ex in exchanges:
            results[ex] = self.get_confirmation(ex, instrument)
        return results

    def aggregate_confirmation(self, confirmations: Dict[str, MarketConfirmation]) -> MarketConfirmation:
        """Aggregate confirmations from multiple exchanges into one."""
        if not confirmations:
            return MarketConfirmation(
                instrument=InstrumentType.SPOT,
                symbol="BTC/USDT",
                exchange="aggregate",
                recent_sell_volume=0,
                recent_buy_volume=0,
                trade_direction_bias=0,
                fetch_success=False,
                fetch_error="No confirmations provided"
            )

        # Aggregate values
        total_sell = sum(c.recent_sell_volume for c in confirmations.values())
        total_buy = sum(c.recent_buy_volume for c in confirmations.values())
        total_vol = total_sell + total_buy

        # Weighted average funding rate
        funding_rates = [c.funding_rate for c in confirmations.values() if c.funding_rate is not None]
        avg_funding = sum(funding_rates) / len(funding_rates) if funding_rates else None

        # Sum of open interest
        total_oi = sum(c.open_interest for c in confirmations.values())
        avg_oi_change = sum(c.open_interest_change_pct for c in confirmations.values()) / len(confirmations)

        first = list(confirmations.values())[0]

        return MarketConfirmation(
            instrument=first.instrument,
            symbol="BTC/USDT",
            exchange="aggregate",
            recent_sell_volume=total_sell,
            recent_buy_volume=total_buy,
            trade_direction_bias=(total_buy - total_sell) / total_vol if total_vol > 0 else 0,
            funding_rate=avg_funding,
            funding_bias="SHORT" if avg_funding and avg_funding > 0 else "LONG" if avg_funding and avg_funding < 0 else "NEUTRAL",
            open_interest=total_oi,
            open_interest_change_pct=avg_oi_change,
        )


# Singleton instance
_pipeline: Optional[CCXTDataPipeline] = None


def get_pipeline() -> CCXTDataPipeline:
    """Get or create the CCXT data pipeline singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = CCXTDataPipeline()
    return _pipeline
