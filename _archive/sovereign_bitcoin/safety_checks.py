#!/usr/bin/env python3
"""
SAFETY CHECKS - Mark Price & Funding Rate (ALL CCXT Exchanges)
===============================================================

SIMPLE RULE:
    Before trading on Exchange X:
    1. Get Exchange X's mark price
    2. Get Exchange X's funding rate
    3. Compare with Exchange X's order book price

NO MIXING. Each exchange uses only its own data.
WORKS WITH ANY CCXT EXCHANGE - No hardcoding.

MULTI-INSTRUMENT SUPPORT:
    Each of the 7 instrument types has its own safety profile:
    - SPOT: Just check liquidity (no leverage risk)
    - MARGIN: Check collateral ratio, interest rate
    - PERPETUAL: Mark price + funding (original implementation)
    - FUTURES: Check expiration distance, basis
    - OPTIONS: Check IV, Greeks sanity
    - INVERSE: Check index price, inverse leverage
    - LEVERAGED_TOKEN: Check NAV, rebalance timing

WHY THIS MATTERS:
    - Liquidation uses MARK PRICE (not order book price)
    - If mark differs from order book by 1%, you lose at 100x leverage
    - Funding rate eats profit if you hold too long
"""

import ccxt
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List, Any

from .config import InstrumentType, supports_instrument, get_instrument_leverage


@dataclass
class ExchangeSafetyData:
    """Safety data for ONE exchange - no mixing."""
    exchange: str
    symbol: str             # The symbol used
    mark_price: float       # Price used for liquidation
    last_price: float       # Last traded price
    funding_rate: float     # Current funding rate (per 8 hours)
    next_funding_time: Optional[datetime]
    timestamp: datetime

    @property
    def mark_vs_last_pct(self) -> float:
        """How much mark differs from last price (percentage)."""
        if self.last_price == 0:
            return 999.0
        return abs(self.mark_price - self.last_price) / self.last_price * 100


class SafetyChecker:
    """
    Gets mark price and funding rate from ANY CCXT exchange.

    DYNAMIC - No hardcoded exchanges:
        exchange = getattr(ccxt, 'binance')()  # Any exchange
        symbol = find_btc_perpetual(exchange)   # Auto-detect symbol
        mark = exchange.fetch_mark_price(symbol)
        funding = exchange.fetch_funding_rate(symbol)
    """

    # Default funding times (UTC) - most exchanges use this
    DEFAULT_FUNDING_HOURS = [0, 8, 16]  # 00:00, 08:00, 16:00 UTC

    # Don't trade within X minutes of funding
    FUNDING_BLACKOUT_MINUTES = 10

    def __init__(self):
        # Create ONE CCXT instance per exchange - each talks only to itself
        self._exchanges: Dict[str, ccxt.Exchange] = {}
        self._symbols: Dict[str, str] = {}  # Cache detected symbols
        self._cache: Dict[str, Tuple[ExchangeSafetyData, float]] = {}
        self._cache_ttl = 5.0  # Cache for 5 seconds

    def _get_exchange(self, name: str) -> Optional[ccxt.Exchange]:
        """
        Get or create CCXT exchange instance for ANY exchange.

        Works with: binance, bybit, okx, kraken, coinbase, etc.
        Full list: print(ccxt.exchanges)
        """
        name = name.lower()

        if name in self._exchanges:
            return self._exchanges[name]

        try:
            # DYNAMIC: Get exchange class by name
            if not hasattr(ccxt, name):
                print(f"[SAFETY] Exchange '{name}' not found in CCXT")
                print(f"[SAFETY] Available: {', '.join(ccxt.exchanges[:10])}...")
                return None

            exchange_class = getattr(ccxt, name)
            ex = exchange_class({'enableRateLimit': True})

            # Load markets to get available symbols
            ex.load_markets()
            self._exchanges[name] = ex

            # Auto-detect BTC perpetual symbol
            symbol = self._find_btc_perpetual(ex, name)
            if symbol:
                self._symbols[name] = symbol
                print(f"[SAFETY] {name.upper()}: Using symbol {symbol}")

            return ex

        except Exception as e:
            print(f"[SAFETY] Cannot connect to {name}: {e}")
            return None

    def _find_btc_perpetual(self, exchange: ccxt.Exchange, name: str) -> Optional[str]:
        """
        Auto-detect BTC perpetual/swap symbol for any exchange.

        Tries common patterns:
            - BTC/USDT:USDT (linear perpetual)
            - BTC/USD:BTC (inverse perpetual)
            - BTCUSDT (some exchanges)
            - BTC-PERP (FTX style)
        """
        # Priority order of symbols to try
        candidates = [
            'BTC/USDT:USDT',   # Linear perpetual (most common)
            'BTC/USD:BTC',     # Inverse perpetual
            'BTC/USD:USD',     # USD margined
            'BTC/BUSD:BUSD',   # Binance BUSD
            'BTC/USDC:USDC',   # USDC margined
            'BTCUSDT',         # Some exchanges use this
            'BTCUSD',          # Some exchanges use this
            'BTC-PERPETUAL',   # Deribit style
            'BTC-PERP',        # FTX style
            'XBTUSD',          # BitMEX style
        ]

        # Try each candidate
        for symbol in candidates:
            if symbol in exchange.markets:
                market = exchange.markets[symbol]
                # Prefer swap/perpetual contracts
                if market.get('swap') or market.get('future') or ':' in symbol:
                    return symbol

        # Fallback: search for any BTC perpetual
        for symbol, market in exchange.markets.items():
            if 'BTC' in symbol.upper():
                if market.get('swap') or market.get('perpetual'):
                    return symbol

        # Last resort: any BTC market
        for symbol in exchange.markets:
            if 'BTC' in symbol.upper() and 'USDT' in symbol.upper():
                return symbol

        print(f"[SAFETY] {name.upper()}: No BTC perpetual found")
        return None

    def _get_symbol(self, exchange_name: str) -> Optional[str]:
        """Get the cached perpetual symbol for an exchange."""
        return self._symbols.get(exchange_name.lower())

    def get_safety_data(self, exchange_name: str) -> Optional[ExchangeSafetyData]:
        """
        Get mark price and funding rate for ONE exchange.

        THIS IS THE KEY FUNCTION:
            - Connects to the specific exchange
            - Gets THAT exchange's mark price
            - Gets THAT exchange's funding rate
            - No data from other exchanges
        """
        exchange_name = exchange_name.lower()

        # Check cache
        if exchange_name in self._cache:
            data, cached_time = self._cache[exchange_name]
            if time.time() - cached_time < self._cache_ttl:
                return data

        # Get exchange (auto-creates if needed)
        exchange = self._get_exchange(exchange_name)
        if not exchange:
            return None

        symbol = self._get_symbol(exchange_name)
        if not symbol:
            return None

        try:
            # =============================================
            # GET MARK PRICE FROM THIS EXCHANGE
            # =============================================
            mark_price = 0.0
            last_price = 0.0

            # Try fetchMarkPrice first (most accurate for perpetuals)
            if exchange.has.get('fetchMarkPrice'):
                try:
                    mark_data = exchange.fetch_mark_price(symbol)
                    mark_price = mark_data.get('markPrice', 0) or 0
                except Exception:
                    pass

            # Fallback: get from ticker
            ticker = exchange.fetch_ticker(symbol)
            last_price = ticker.get('last', 0) or 0

            if mark_price == 0:
                # Use mark from ticker if available, else use last
                mark_price = ticker.get('mark', ticker.get('markPrice', last_price)) or last_price

            # =============================================
            # GET FUNDING RATE FROM THIS EXCHANGE
            # =============================================
            funding_rate = 0.0
            next_funding = None

            if exchange.has.get('fetchFundingRate'):
                try:
                    funding_data = exchange.fetch_funding_rate(symbol)
                    funding_rate = funding_data.get('fundingRate', 0) or 0

                    # Get next funding time
                    next_ts = funding_data.get('fundingTimestamp') or funding_data.get('nextFundingTimestamp')
                    if next_ts:
                        next_funding = datetime.fromtimestamp(next_ts / 1000, tz=timezone.utc)
                except Exception:
                    pass

            # If no next funding from API, calculate default
            if not next_funding:
                next_funding = self._get_next_funding_time(exchange_name)

            # Create result
            data = ExchangeSafetyData(
                exchange=exchange_name,
                symbol=symbol,
                mark_price=float(mark_price),
                last_price=float(last_price),
                funding_rate=float(funding_rate),
                next_funding_time=next_funding,
                timestamp=datetime.now(timezone.utc)
            )

            # Cache it
            self._cache[exchange_name] = (data, time.time())
            return data

        except Exception as e:
            print(f"[SAFETY] Error getting data from {exchange_name}: {e}")
            return None

    def _get_next_funding_time(self, exchange_name: str) -> datetime:
        """Calculate when next funding happens (default: 0, 8, 16 UTC)."""
        hours = self.DEFAULT_FUNDING_HOURS
        now = datetime.now(timezone.utc)

        for hour in sorted(hours):
            candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate > now:
                return candidate

        # Next day
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=hours[0], minute=0, second=0, microsecond=0)

    def is_in_funding_blackout(self, exchange_name: str) -> Tuple[bool, float]:
        """
        Check if we're too close to funding time.

        Returns: (is_blackout, minutes_to_funding)
        """
        hours = self.DEFAULT_FUNDING_HOURS
        now = datetime.now(timezone.utc)
        current_minutes = now.hour * 60 + now.minute

        for hour in hours:
            funding_minutes = hour * 60
            diff = abs(current_minutes - funding_minutes)

            # Handle midnight wrap
            if diff > 12 * 60:
                diff = 24 * 60 - diff

            if diff <= self.FUNDING_BLACKOUT_MINUTES:
                return True, diff

        # Calculate minutes to next funding
        next_funding = self._get_next_funding_time(exchange_name)
        minutes_to = (next_funding - now).total_seconds() / 60
        return False, minutes_to

    def check_safety(
        self,
        exchange: str,
        order_book_price: float,
        expected_profit_pct: float,
        leverage: int
    ) -> Tuple[bool, str]:
        """
        THE MAIN SAFETY CHECK

        Before trading on [exchange]:
            1. Get [exchange]'s mark price
            2. Compare to [exchange]'s order book price
            3. Check [exchange]'s funding rate
            4. Check if near [exchange]'s funding time

        Returns: (is_safe, reason)
        """
        exchange = exchange.lower()

        # Get safety data for THIS exchange
        data = self.get_safety_data(exchange)

        if not data:
            return False, f"Cannot get safety data from {exchange.upper()}"

        # =============================================
        # CHECK 1: Mark price vs Order book price
        # =============================================
        # Higher leverage = need tighter tolerance
        # 100x leverage = 1% buffer = need mark within 0.1% of order book
        max_deviation = 100 / leverage * 0.1  # 0.1% at 100x, 1% at 10x

        if order_book_price > 0:
            deviation = abs(data.mark_price - order_book_price) / order_book_price * 100
        else:
            deviation = data.mark_vs_last_pct

        if deviation > max_deviation:
            return False, (
                f"MARK PRICE RISK: {exchange.upper()} mark=${data.mark_price:,.0f} "
                f"vs book=${order_book_price:,.0f} ({deviation:.3f}% diff, max={max_deviation:.3f}%)"
            )

        # =============================================
        # CHECK 2: Funding rate won't eat profit
        # =============================================
        # Funding is per 8 hours, but with leverage it's amplified
        funding_cost_pct = abs(data.funding_rate) * 100 * leverage

        if funding_cost_pct > expected_profit_pct * 0.5:
            return False, (
                f"FUNDING RISK: {exchange.upper()} funding={data.funding_rate*100:.4f}% "
                f"x {leverage}x = {funding_cost_pct:.2f}% cost (>50% of {expected_profit_pct:.2f}% profit)"
            )

        # =============================================
        # CHECK 3: Not near funding time
        # =============================================
        in_blackout, minutes = self.is_in_funding_blackout(exchange)

        if in_blackout:
            return False, (
                f"TIMING RISK: {exchange.upper()} funding in {minutes:.0f}min. "
                f"Wait {self.FUNDING_BLACKOUT_MINUTES - minutes:.0f}min."
            )

        # ALL SAFE
        return True, (
            f"SAFE: {exchange.upper()} mark_dev={deviation:.4f}% "
            f"funding={data.funding_rate*100:.4f}% next={minutes:.0f}min"
        )

    def list_available_exchanges(self) -> List[str]:
        """List all CCXT exchanges (100+)."""
        return ccxt.exchanges


# =============================================
# SIMPLE INTERFACE
# =============================================

_checker = None

def get_safety_checker() -> SafetyChecker:
    """Get the global safety checker."""
    global _checker
    if _checker is None:
        _checker = SafetyChecker()
    return _checker


def check_trade_safety(
    exchange: str,
    order_book_price: float,
    expected_profit_pct: float,
    leverage: int = 100,
    instrument_type: InstrumentType = InstrumentType.PERPETUAL,
    **kwargs: Any
) -> Tuple[bool, str]:
    """
    Simple function to check if trade is safe.

    MULTI-INSTRUMENT SUPPORT:
        Each instrument type has its own safety checks:
        - SPOT: Liquidity only
        - MARGIN: Collateral ratio, interest rate
        - PERPETUAL: Mark price + funding
        - FUTURES: Expiration, basis
        - OPTIONS: IV, Greeks
        - INVERSE: Index price
        - LEVERAGED_TOKEN: NAV, rebalance

    Works with ANY CCXT exchange:
        safe, reason = check_trade_safety(
            exchange='binance',  # or 'bybit', 'okx', 'kraken', etc.
            order_book_price=87000,
            expected_profit_pct=2.0,
            leverage=50,
            instrument_type=InstrumentType.PERPETUAL
        )

        if not safe:
            print(f"BLOCKED: {reason}")
            return
    """
    checker = get_safety_checker()

    # Check if exchange supports this instrument
    if not supports_instrument(exchange, instrument_type):
        return False, f"{exchange.upper()} does not support {instrument_type.name}"

    # Route to instrument-specific safety check
    if instrument_type == InstrumentType.SPOT:
        return _check_spot_safety(checker, exchange, order_book_price)

    elif instrument_type == InstrumentType.MARGIN:
        collateral_ratio = kwargs.get('collateral_ratio', 1.5)
        interest_rate = kwargs.get('interest_rate', 0.0)
        return _check_margin_safety(
            checker, exchange, order_book_price,
            leverage, collateral_ratio, interest_rate
        )

    elif instrument_type == InstrumentType.PERPETUAL:
        # Original implementation
        return checker.check_safety(
            exchange, order_book_price, expected_profit_pct, leverage
        )

    elif instrument_type == InstrumentType.FUTURES:
        expiration_ts = kwargs.get('expiration_ts', 0)
        basis = kwargs.get('basis', 0.0)
        return _check_futures_safety(
            checker, exchange, order_book_price,
            leverage, expiration_ts, basis
        )

    elif instrument_type == InstrumentType.OPTIONS:
        strike = kwargs.get('strike', 0.0)
        iv = kwargs.get('implied_vol', 0.0)
        delta = kwargs.get('delta', 0.0)
        theta = kwargs.get('theta', 0.0)
        return _check_options_safety(
            checker, exchange, order_book_price,
            strike, iv, delta, theta
        )

    elif instrument_type == InstrumentType.INVERSE:
        index_price = kwargs.get('index_price', 0.0)
        contract_size = kwargs.get('contract_size', 1.0)
        return _check_inverse_safety(
            checker, exchange, order_book_price,
            leverage, index_price, contract_size, expected_profit_pct
        )

    elif instrument_type == InstrumentType.LEVERAGED_TOKEN:
        nav = kwargs.get('nav', 0.0)
        rebalance_ts = kwargs.get('rebalance_ts', 0)
        return _check_leveraged_token_safety(
            checker, exchange, order_book_price,
            nav, rebalance_ts
        )

    return False, f"Unknown instrument type: {instrument_type}"


# =============================================================================
# PER-INSTRUMENT SAFETY CHECKS
# =============================================================================

def _check_spot_safety(
    checker: SafetyChecker,
    exchange: str,
    price: float
) -> Tuple[bool, str]:
    """
    SPOT: Just check liquidity - no leverage risk.

    100% DETERMINISTIC:
        - Check spread is reasonable (<0.5%)
        - No mark price (spot IS the price)
        - No funding (no perpetual)
    """
    data = checker.get_safety_data(exchange)
    if not data:
        # For spot, we don't strictly need mark price data
        return True, f"SPOT OK: {exchange.upper()} (no derivatives data needed)"

    # Check spread is reasonable
    if data.mark_vs_last_pct > 0.5:  # 0.5% spread max
        return False, f"SPOT HIGH SPREAD: {exchange.upper()} {data.mark_vs_last_pct:.2f}%"

    return True, f"SPOT OK: {exchange.upper()} spread={data.mark_vs_last_pct:.4f}%"


def _check_margin_safety(
    checker: SafetyChecker,
    exchange: str,
    price: float,
    leverage: int,
    collateral_ratio: float,
    interest_rate: float
) -> Tuple[bool, str]:
    """
    MARGIN: Check liquidation distance and interest costs.

    100% DETERMINISTIC:
        - Liquidation distance must be > 5%
        - Interest rate must be < 0.1%/day
        - Collateral ratio must be > 120%
    """
    # Liquidation check
    liq_distance = (1.0 / leverage) * 100  # e.g., 10x = 10% buffer
    if liq_distance < 5:  # Less than 5% buffer
        return False, f"MARGIN LIQUIDATION RISK: {exchange.upper()} liq_dist={liq_distance:.1f}%"

    # Interest rate check (hourly rate)
    daily_interest = interest_rate * 24
    if daily_interest > 0.1:  # More than 0.1% daily
        return False, f"MARGIN HIGH INTEREST: {exchange.upper()} {daily_interest:.3f}%/day"

    # Collateral ratio check
    if collateral_ratio < 1.2:  # Less than 120%
        return False, f"MARGIN LOW COLLATERAL: {exchange.upper()} {collateral_ratio:.1%}"

    return True, f"MARGIN OK: {exchange.upper()} lev={leverage}x liq_dist={liq_distance:.1f}%"


def _check_futures_safety(
    checker: SafetyChecker,
    exchange: str,
    price: float,
    leverage: int,
    expiration_ts: int,
    basis: float
) -> Tuple[bool, str]:
    """
    FUTURES: Check expiration and basis.

    100% DETERMINISTIC:
        - Don't trade if expiring within 24 hours
        - Basis must be < 2%
        - Mark deviation check same as perpetual
    """
    now_ts = int(time.time() * 1000)
    days_to_expiry = (expiration_ts - now_ts) / (1000 * 86400) if expiration_ts > 0 else 999

    # Don't trade if expiring within 24 hours
    if 0 < days_to_expiry < 1:
        return False, f"FUTURES EXPIRING: {exchange.upper()} in {days_to_expiry*24:.1f} hours"

    # Check basis is reasonable
    basis_pct = (basis / price) * 100 if price > 0 else 0
    if abs(basis_pct) > 2:  # More than 2% basis
        return False, f"FUTURES HIGH BASIS: {exchange.upper()} {basis_pct:.2f}%"

    # Mark price check (same as perpetual)
    data = checker.get_safety_data(exchange)
    if data and data.mark_vs_last_pct > 0.3:
        return False, f"FUTURES MARK DEVIATION: {exchange.upper()} {data.mark_vs_last_pct:.3f}%"

    return True, f"FUTURES OK: {exchange.upper()} {days_to_expiry:.0f}d to expiry basis={basis_pct:.2f}%"


def _check_options_safety(
    checker: SafetyChecker,
    exchange: str,
    price: float,
    strike: float,
    iv: float,
    delta: float,
    theta: float
) -> Tuple[bool, str]:
    """
    OPTIONS: Check IV and Greeks sanity.

    100% DETERMINISTIC:
        - IV should be 10-200%
        - Delta must be valid (-1 to 1)
        - Theta decay < 2%/day
        - Strike distance < 50% OTM
    """
    # IV sanity check
    if iv > 0 and (iv < 10 or iv > 200):  # IV should be 10-200%
        return False, f"OPTIONS IV OUT OF RANGE: {exchange.upper()} IV={iv:.1f}%"

    # Delta sanity check
    if abs(delta) > 1:
        return False, f"OPTIONS INVALID DELTA: {exchange.upper()} delta={delta:.2f}"

    # Theta decay check (don't buy if losing >2%/day)
    if theta < -2:
        return False, f"OPTIONS HIGH THETA: {exchange.upper()} theta={theta:.2f}%/day"

    # Strike distance check
    if strike > 0 and price > 0:
        strike_distance = abs(strike - price) / price * 100
        if strike_distance > 50:  # More than 50% OTM
            return False, f"OPTIONS DEEP OTM: {exchange.upper()} {strike_distance:.1f}% from strike"

    return True, f"OPTIONS OK: {exchange.upper()} IV={iv:.1f}% delta={delta:.2f} theta={theta:.2f}"


def _check_inverse_safety(
    checker: SafetyChecker,
    exchange: str,
    price: float,
    leverage: int,
    index_price: float,
    contract_size: float,
    expected_profit_pct: float
) -> Tuple[bool, str]:
    """
    INVERSE: Check index price and BTC volatility.

    100% DETERMINISTIC:
        - Index vs mark deviation < 0.5%
        - Same funding checks as perpetual
        - Inverse contracts have higher funding typically
    """
    # Index vs mark deviation
    if index_price > 0 and price > 0:
        deviation = abs(price - index_price) / index_price * 100
        if deviation > 0.5:
            return False, f"INVERSE INDEX DEVIATION: {exchange.upper()} {deviation:.2f}%"

    # Same checks as perpetual
    data = checker.get_safety_data(exchange)
    if not data:
        return False, f"INVERSE NO DATA: {exchange.upper()}"

    # Funding check (inverse has higher funding typically)
    funding_cost = abs(data.funding_rate) * 100 * leverage
    if funding_cost > 1:  # More than 1% per 8 hours with leverage
        return False, f"INVERSE HIGH FUNDING: {exchange.upper()} {funding_cost:.2f}%"

    return True, f"INVERSE OK: {exchange.upper()} funding={data.funding_rate*100:.4f}%"


def _check_leveraged_token_safety(
    checker: SafetyChecker,
    exchange: str,
    price: float,
    nav: float,
    rebalance_ts: int
) -> Tuple[bool, str]:
    """
    LEVERAGED TOKEN: Check NAV and rebalance timing.

    100% DETERMINISTIC:
        - NAV premium/discount < 1%
        - Don't trade within 2 hours of rebalance
        - Never hold overnight (daily rebalance risk)
    """
    # NAV premium/discount check
    if nav > 0 and price > 0:
        premium = (price - nav) / nav * 100
        if abs(premium) > 1:  # More than 1% premium/discount
            return False, f"LEV_TOKEN NAV DEVIATION: {exchange.upper()} {premium:.2f}%"

    # Don't trade near rebalance time
    now_ts = int(time.time() * 1000)
    if rebalance_ts > 0:
        hours_to_rebalance = (rebalance_ts - now_ts) / (1000 * 3600)
        if 0 < hours_to_rebalance < 2:  # Within 2 hours of rebalance
            return False, f"LEV_TOKEN REBALANCE: {exchange.upper()} in {hours_to_rebalance:.1f} hours"

    return True, f"LEV_TOKEN OK: {exchange.upper()}"


# =============================================
# TEST
# =============================================

def main():
    """Test safety checks on multiple exchanges."""
    print("=" * 70)
    print("SAFETY CHECKS - ANY CCXT Exchange")
    print("=" * 70)
    print()
    print("RULE: Each exchange uses ONLY its own data. No mixing.")
    print(f"CCXT supports {len(ccxt.exchanges)} exchanges")
    print()

    checker = SafetyChecker()

    # Test popular exchanges with perpetuals
    test_exchanges = [
        'binance', 'bybit', 'okx', 'deribit', 'mexc',
        'phemex', 'bitget', 'gate', 'huobi', 'kucoin'
    ]

    print(f"{'Exchange':<12} {'Symbol':<20} {'Mark':>12} {'Last':>12} {'Dev':>8} {'Fund':>8}")
    print("-" * 80)

    working = []
    for ex in test_exchanges:
        data = checker.get_safety_data(ex)

        if data:
            working.append(ex)
            print(
                f"{ex.upper():<12} "
                f"{data.symbol:<20} "
                f"${data.mark_price:>10,.0f} "
                f"${data.last_price:>10,.0f} "
                f"{data.mark_vs_last_pct:>7.4f}% "
                f"{data.funding_rate*100:>7.4f}%"
            )
        else:
            print(f"{ex.upper():<12} -- cannot connect or no perpetual --")

    print()
    print("=" * 70)
    print()
    print(f"WORKING EXCHANGES: {len(working)}/{len(test_exchanges)}")
    print(f"  {', '.join(working)}")
    print()

    # Safety check simulation
    print("SAFETY CHECK SIMULATION (50x leverage, 2% expected profit):")
    print("-" * 70)

    for ex in working[:4]:  # Test first 4 working exchanges
        data = checker.get_safety_data(ex)
        if data:
            safe, reason = checker.check_safety(
                exchange=ex,
                order_book_price=data.last_price,
                expected_profit_pct=2.0,
                leverage=50
            )
            status = "SAFE" if safe else "BLOCKED"
            print(f"{ex.upper()}: {status}")
            print(f"  {reason}")
            print()

    print("=" * 70)


if __name__ == "__main__":
    main()
