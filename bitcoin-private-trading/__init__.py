#!/usr/bin/env python3
"""
==============================================================================
SOVEREIGN HFT TRADING ENGINE
==============================================================================

ARCHITECTURE:
    C++ = Fast data extraction (order books, nanosecond speed)
    Python = Business logic (signals, trading decisions)

TRADING EDGE:
    INFLOW  -> SHORT (sellers depositing to sell)
    OUTFLOW -> LONG  (seller exhaustion)

DETERMINISTIC FORMULA:
    IF price_impact > 2 * fees THEN guaranteed_profit

MODULES:
    config          - 23 exchanges, 7 instruments, all configuration
    signals         - Signal generation (CorrelationFormula)
    trader          - Position management (DeterministicTrader)  
    price_feed      - Multi-exchange price feeds (CCXT)
    cpp_orderbook   - C++ order book bridge (<1ms reads)
    depth_calculator- Price impact calculations
    safety_checks   - Per-instrument safety validation
    signal_simulator- Paper trading signal generator
    main            - Entry point

EXCHANGES (23 verified working):
    US Direct:      coinbase, gemini, kraken, bitstamp
    International:  okx, htx, kucoin, gate, mexc, bitget, phemex, deribit,
                    poloniex, bitfinex, coinex, bingx, bitmart, lbank,
                    whitebit, cryptocom, xt, probit, ascendex

USAGE:
    # Paper trading
    python -m bitcoin.signal_simulator --rate 3
    
    # Full engine
    python -m bitcoin.main --paper

==============================================================================
"""

__version__ = "2.0.0"
__author__ = "Sovereign Trading"

# Core exports
from .config import (
    TradingConfig,
    get_config,
    InstrumentType,
    EXCHANGE_INSTRUMENTS,
    VERIFIED_EXCHANGES,
)

from .signals import (
    Signal,
    SignalType,
    CorrelationFormula,
)

from .trader import (
    Position,
    DeterministicTrader,
)

from .cpp_orderbook import (
    CppOrderBook,
)

from .depth_calculator import (
    calculate_price_impact,
    PriceImpact,
)

from .safety_checks import (
    check_trade_safety,
    SafetyChecker,
)

# Aliases for backwards compatibility
OrderFlow = CppOrderBook

__all__ = [
    # Config
    "TradingConfig",
    "get_config", 
    "InstrumentType",
    "EXCHANGE_INSTRUMENTS",
    "VERIFIED_EXCHANGES",
    # Signals
    "Signal",
    "SignalType", 
    "CorrelationFormula",
    # Trading
    "Position",
    "DeterministicTrader",
    # Order books
    "CppOrderBook",
    "OrderFlow",
    # Calculations
    "calculate_price_impact",
    "PriceImpact",
    # Safety
    "check_trade_safety",
    "SafetyChecker",
]
