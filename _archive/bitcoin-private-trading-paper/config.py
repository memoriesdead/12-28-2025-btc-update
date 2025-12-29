#!/usr/bin/env python3
"""
==============================================================================
TRADING CONFIGURATION
==============================================================================

This module contains all configuration for the trading engine:
- 23 verified working exchanges
- 7 trading instrument types
- Exchange-instrument support matrix
- Trading parameters

==============================================================================
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Set, List


class InstrumentType(Enum):
    """All 7 trading instrument types."""
    SPOT = auto()            # 1x, own the asset
    MARGIN = auto()          # 3-10x, collateral-based
    PERPETUAL = auto()       # up to 125x, funding every 8hrs
    FUTURES = auto()         # up to 100x, expiration dates
    OPTIONS = auto()         # Premium-based, Greeks
    INVERSE = auto()         # BTC-denominated contracts
    LEVERAGED_TOKEN = auto() # Fixed 3x, daily rebalance


# US exchanges - work directly from VPS
US_EXCHANGES = ["coinbase", "gemini", "kraken", "bitstamp"]

# International exchanges - require Frankfurt proxy
INTERNATIONAL_EXCHANGES = [
    "okx", "htx", "kucoin", "gate", "mexc", "bitget", "phemex", "deribit",
    "poloniex", "bitfinex", "coinex", "bingx", "bitmart", "lbank",
    "whitebit", "cryptocom", "xt", "probit", "ascendex"
]

# All 23 verified working exchanges
VERIFIED_EXCHANGES = US_EXCHANGES + INTERNATIONAL_EXCHANGES


# Exchange-instrument support matrix
EXCHANGE_INSTRUMENTS: Dict[str, Set[InstrumentType]] = {
    # US EXCHANGES
    "coinbase": {InstrumentType.SPOT},
    "gemini": {InstrumentType.SPOT, InstrumentType.PERPETUAL},
    "kraken": {InstrumentType.SPOT, InstrumentType.MARGIN},
    "bitstamp": {InstrumentType.SPOT},
    # INTERNATIONAL
    "okx": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL,
            InstrumentType.FUTURES, InstrumentType.OPTIONS, InstrumentType.INVERSE},
    "htx": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL,
            InstrumentType.FUTURES, InstrumentType.INVERSE},
    "kucoin": {InstrumentType.SPOT, InstrumentType.MARGIN},
    "gate": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL,
             InstrumentType.FUTURES, InstrumentType.OPTIONS, InstrumentType.LEVERAGED_TOKEN},
    "mexc": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL,
             InstrumentType.FUTURES, InstrumentType.LEVERAGED_TOKEN},
    "bitget": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL, InstrumentType.FUTURES},
    "phemex": {InstrumentType.SPOT, InstrumentType.PERPETUAL, InstrumentType.FUTURES, InstrumentType.INVERSE},
    "deribit": {InstrumentType.PERPETUAL, InstrumentType.FUTURES, InstrumentType.OPTIONS, InstrumentType.INVERSE},
    "poloniex": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL},
    "bitfinex": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL},
    "coinex": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL, InstrumentType.FUTURES},
    "bingx": {InstrumentType.SPOT, InstrumentType.PERPETUAL, InstrumentType.FUTURES},
    "bitmart": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL},
    "lbank": {InstrumentType.SPOT, InstrumentType.PERPETUAL},
    "whitebit": {InstrumentType.SPOT, InstrumentType.PERPETUAL},
    "cryptocom": {InstrumentType.SPOT, InstrumentType.PERPETUAL},
    "xt": {InstrumentType.SPOT, InstrumentType.PERPETUAL},
    "probit": {InstrumentType.SPOT},
    "ascendex": {InstrumentType.SPOT, InstrumentType.MARGIN, InstrumentType.PERPETUAL},
}


# Leverage limits per instrument
INSTRUMENT_MAX_LEVERAGE: Dict[InstrumentType, int] = {
    InstrumentType.SPOT: 1,
    InstrumentType.MARGIN: 10,
    InstrumentType.PERPETUAL: 125,
    InstrumentType.FUTURES: 100,
    InstrumentType.OPTIONS: 1,
    InstrumentType.INVERSE: 100,
    InstrumentType.LEVERAGED_TOKEN: 3,
}

# Priority order (higher leverage = higher priority)
INSTRUMENT_PRIORITY = [
    InstrumentType.PERPETUAL, InstrumentType.FUTURES, InstrumentType.INVERSE,
    InstrumentType.MARGIN, InstrumentType.LEVERAGED_TOKEN, InstrumentType.SPOT,
]

# Frankfurt proxy
FRANKFURT_PROXY = {"ip": "141.147.58.130", "port": 8888, "url": "http://141.147.58.130:8888"}


@dataclass
class TradingConfig:
    """Complete trading configuration."""
    initial_capital: float = 100.0
    max_positions: int = 4
    position_size_pct: float = 0.25
    max_leverage: int = 125
    default_leverage: int = 20
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.02
    exit_timeout_seconds: int = 300
    maker_fee_pct: float = 0.02
    taker_fee_pct: float = 0.05
    min_flow_btc: float = 5.0
    min_impact_multiple: float = 2.0
    signal_cooldown_seconds: int = 60
    price_check_interval_ms: int = 100
    exchanges: List[str] = field(default_factory=lambda: VERIFIED_EXCHANGES.copy())
    use_proxy: bool = True
    proxy_url: str = FRANKFURT_PROXY["url"]


def get_config() -> TradingConfig:
    """Get default trading configuration."""
    return TradingConfig()


def get_instruments(exchange: str) -> Set[InstrumentType]:
    """Get supported instruments for an exchange."""
    return EXCHANGE_INSTRUMENTS.get(exchange.lower(), {InstrumentType.SPOT})


def get_best_instrument(exchange: str) -> InstrumentType:
    """Get highest priority instrument for an exchange."""
    supported = get_instruments(exchange)
    for inst in INSTRUMENT_PRIORITY:
        if inst in supported:
            return inst
    return InstrumentType.SPOT


def get_max_leverage(instrument: InstrumentType) -> int:
    """Get maximum leverage for an instrument type."""
    return INSTRUMENT_MAX_LEVERAGE.get(instrument, 1)


def needs_proxy(exchange: str) -> bool:
    """Check if exchange needs Frankfurt proxy."""
    return exchange.lower() in INTERNATIONAL_EXCHANGES


if __name__ == "__main__":
    print(f"Exchanges: {len(VERIFIED_EXCHANGES)}")
    print(f"US: {US_EXCHANGES}")
    print(f"International: {len(INTERNATIONAL_EXCHANGES)}")


# Aliases for backwards compatibility
get_instrument_leverage = get_max_leverage


def supports_instrument(exchange: str, instrument: InstrumentType) -> bool:
    """Check if exchange supports an instrument type."""
    supported = get_instruments(exchange)
    return instrument in supported


# Database paths
CORRELATION_DB_PATH = "/root/sovereign/correlation.db"
TRADES_DB_PATH = "/root/sovereign/trades.db"


# Add paths to TradingConfig
TradingConfig.correlation_db_path = CORRELATION_DB_PATH
TradingConfig.trades_db_path = TRADES_DB_PATH
TradingConfig.cpp_orderbook_path = "/tmp/orderbooks.json"


# Additional config attributes for main.py
TradingConfig.addresses_db_path = "/root/sovereign/walletexplorer_addresses.db"
TradingConfig.cpp_runner_path = "/root/sovereign/cpp_runner/build/blockchain_runner"
TradingConfig.fees_pct = 0.0005  # 0.05%
TradingConfig.min_deposit_btc = 5.0
TradingConfig.order_book_depth = 100
TradingConfig.take_profit_ratio = 2.0
TradingConfig.tradeable_exchanges = VERIFIED_EXCHANGES
TradingConfig.get_leverage = lambda self, ex: 20  # Default leverage

# Method to check if exchange is tradeable
def _is_tradeable(self, exchange):
    return exchange.lower() in [ex.lower() for ex in VERIFIED_EXCHANGES]
TradingConfig.is_tradeable = _is_tradeable


# Method to get fee for exchange
def _get_fee(self, exchange):
    return self.fees_pct
TradingConfig.get_fee = _get_fee

