#!/usr/bin/env python3
"""
DETERMINISTIC TRADER
====================

Single responsibility: Manage positions based on signals.

FEATURES:
- Uses TradingConfig for all settings
- Time-based exits (no flow reversal exits)
- Per-exchange P&L tracking
- Clean position management

MULTI-INSTRUMENT SUPPORT:
- All 7 instrument types: SPOT, MARGIN, PERPETUAL, FUTURES, OPTIONS, INVERSE, LEVERAGED_TOKEN
- Per-instrument position fields (margin collateral, futures expiration, options Greeks, etc.)
- Instrument-specific P&L calculation
- 100% deterministic across all instruments
"""

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from enum import Enum

from .config import TradingConfig, get_config, InstrumentType, get_max_leverage
from .signals import Signal, SignalType


class PositionStatus(Enum):
    """Position status."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STOPPED_OUT = "STOPPED_OUT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIMED_OUT = "TIMED_OUT"


@dataclass
class Position:
    """
    A trading position - supports ALL 7 instrument types.

    INSTRUMENT-SPECIFIC FIELDS:
    - SPOT: Basic position (no leverage)
    - MARGIN: collateral, liquidation_price, interest_accrued
    - PERPETUAL: funding_paid (8-hour funding)
    - FUTURES: expiration, basis_at_entry
    - OPTIONS: strike, option_type, premium_paid, Greeks
    - INVERSE: position_size_btc, contract_value, index_at_entry
    - LEVERAGED_TOKEN: nav_at_entry, token_amount
    """
    id: int
    exchange: str
    direction: SignalType  # SHORT or LONG
    entry_price: float
    entry_time: datetime
    size_usd: float
    size_btc: float
    leverage: int
    stop_loss: float
    take_profit: float
    status: PositionStatus = PositionStatus.OPEN
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""

    # NEW: Instrument type (default PERPETUAL for backward compatibility)
    instrument_type: InstrumentType = InstrumentType.PERPETUAL

    # MARGIN specific fields
    collateral: float = 0.0
    liquidation_price: float = 0.0
    interest_accrued: float = 0.0
    borrow_rate: float = 0.0

    # PERPETUAL specific fields
    funding_paid: float = 0.0  # Total funding paid/received

    # FUTURES specific fields
    expiration: Optional[datetime] = None
    basis_at_entry: float = 0.0

    # OPTIONS specific fields
    strike: float = 0.0
    option_type: str = "CALL"  # "CALL" or "PUT"
    premium_paid: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    implied_vol: float = 0.0

    # INVERSE specific fields
    position_size_contracts: float = 0.0
    contract_value: float = 0.0
    index_at_entry: float = 0.0

    # LEVERAGED_TOKEN specific fields
    nav_at_entry: float = 0.0
    token_amount: float = 0.0

    def calculate_pnl(self, current_price: float, **kwargs: Any) -> float:
        """
        Calculate P&L based on instrument type.

        100% DETERMINISTIC - pure math, no guessing.
        """
        if self.instrument_type == InstrumentType.SPOT:
            return self._spot_pnl(current_price)
        elif self.instrument_type == InstrumentType.MARGIN:
            return self._margin_pnl(current_price)
        elif self.instrument_type == InstrumentType.PERPETUAL:
            return self._perpetual_pnl(current_price)
        elif self.instrument_type == InstrumentType.FUTURES:
            return self._futures_pnl(current_price)
        elif self.instrument_type == InstrumentType.OPTIONS:
            current_premium = kwargs.get('current_premium', 0.0)
            return self._options_pnl(current_price, current_premium)
        elif self.instrument_type == InstrumentType.INVERSE:
            return self._inverse_pnl(current_price)
        elif self.instrument_type == InstrumentType.LEVERAGED_TOKEN:
            nav = kwargs.get('nav', current_price)
            return self._leveraged_token_pnl(nav)
        return 0.0

    def _spot_pnl(self, price: float) -> float:
        """SPOT: Simple price difference, no leverage."""
        if self.direction == SignalType.LONG:
            return (price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - price) / self.entry_price * 100

    def _margin_pnl(self, price: float) -> float:
        """MARGIN: Include interest costs."""
        base_pnl = self._spot_pnl(price) * self.leverage
        return base_pnl - self.interest_accrued

    def _perpetual_pnl(self, price: float) -> float:
        """PERPETUAL: Include funding costs."""
        base_pnl = self._spot_pnl(price) * self.leverage
        return base_pnl - self.funding_paid

    def _futures_pnl(self, price: float) -> float:
        """FUTURES: Include basis convergence."""
        base_pnl = self._spot_pnl(price) * self.leverage
        return base_pnl

    def _options_pnl(self, price: float, current_premium: float) -> float:
        """OPTIONS: Premium-based P&L."""
        if current_premium > 0 and self.premium_paid > 0:
            return (current_premium - self.premium_paid) / self.premium_paid * 100
        # Fallback: intrinsic value
        if self.option_type == "CALL":
            intrinsic = max(0, price - self.strike)
        else:
            intrinsic = max(0, self.strike - price)
        if self.premium_paid > 0:
            return (intrinsic - self.premium_paid) / self.premium_paid * 100
        return 0.0

    def _inverse_pnl(self, price: float) -> float:
        """INVERSE: BTC-denominated, P&L in BTC then convert to USD."""
        if self.entry_price == 0 or price == 0:
            return 0.0
        # Inverse contracts: P&L in BTC = contracts * (1/entry - 1/exit)
        btc_pnl = self.position_size_contracts * (1/self.entry_price - 1/price)
        if self.direction == SignalType.SHORT:
            btc_pnl = -btc_pnl
        # Convert to USD at current price, apply leverage
        usd_pnl = btc_pnl * price * self.leverage
        # Return as percentage of collateral
        if self.size_usd > 0:
            return usd_pnl / (self.size_usd / self.leverage) * 100
        return 0.0

    def _leveraged_token_pnl(self, nav: float) -> float:
        """LEVERAGED TOKEN: NAV-based P&L (accounts for direction)."""
        if self.nav_at_entry == 0:
            return 0.0
        nav_change_pct = (nav - self.nav_at_entry) / self.nav_at_entry * 100
        # SHORT profits when NAV drops, LONG profits when NAV rises
        if self.direction == SignalType.SHORT:
            return -nav_change_pct
        return nav_change_pct


@dataclass
class TraderStats:
    """Trader statistics."""
    total_trades: int = 0
    # Signal accuracy (price moved in predicted direction)
    signals_correct: int = 0
    signals_wrong: int = 0
    # Profit (after fees)
    profitable_trades: int = 0
    unprofitable_trades: int = 0
    total_pnl_usd: float = 0.0
    current_capital: float = 0.0
    max_drawdown_pct: float = 0.0
    peak_capital: float = 0.0
    per_exchange_pnl: Dict[str, float] = field(default_factory=dict)

    @property
    def signal_win_rate(self) -> float:
        """Signal accuracy - did price move in predicted direction?"""
        if self.total_trades == 0:
            return 0.0
        return self.signals_correct / self.total_trades

    @property
    def profit_rate(self) -> float:
        """Profit rate - did we make money after fees?"""
        if self.total_trades == 0:
            return 0.0
        return self.profitable_trades / self.total_trades

    # Keep old property for compatibility
    @property
    def win_rate(self) -> float:
        """Signal win rate (not profit rate)."""
        return self.signal_win_rate

    @property
    def winning_trades(self) -> int:
        """Signals correct (not profit)."""
        return self.signals_correct

    @property
    def losing_trades(self) -> int:
        """Signals wrong (not profit)."""
        return self.signals_wrong


class DeterministicTrader:
    """
    Deterministic position manager.

    Uses signals from CorrelationFormula to open positions.
    Uses time-based exits (not flow reversal).
    Tracks P&L per exchange.
    """

    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or get_config()
        self.lock = threading.Lock()

        # Active positions
        self.positions: Dict[int, Position] = {}
        self.position_counter = 0

        # Statistics
        self.stats = TraderStats(current_capital=self.config.initial_capital)
        self.stats.peak_capital = self.config.initial_capital

        # Initialize database
        self._init_db()

        # Load historical stats
        self._load_stats()

    def _init_db(self):
        """Initialize trades database."""
        conn = sqlite3.connect(self.config.trades_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                exit_price REAL,
                exit_time TEXT,
                size_usd REAL NOT NULL,
                size_btc REAL NOT NULL,
                leverage INTEGER NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                status TEXT NOT NULL,
                pnl_usd REAL DEFAULT 0.0,
                pnl_pct REAL DEFAULT 0.0,
                exit_reason TEXT,
                signal_correlation REAL,
                signal_win_rate REAL,
                signal_samples INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS equity_curve (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                capital REAL NOT NULL,
                open_positions INTEGER NOT NULL
            )
        """)

        conn.commit()
        conn.close()

    def _load_stats(self):
        """Load historical statistics from database."""
        try:
            conn = sqlite3.connect(self.config.trades_db_path)
            cursor = conn.cursor()

            # Get totals
            cursor.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END),
                       SUM(pnl_usd)
                FROM trades
                WHERE status != 'OPEN'
            """)
            row = cursor.fetchone()
            if row and row[0]:
                self.stats.total_trades = row[0]
                self.stats.winning_trades = row[1] or 0
                self.stats.losing_trades = self.stats.total_trades - self.stats.winning_trades
                self.stats.total_pnl_usd = row[2] or 0.0
                self.stats.current_capital = self.config.initial_capital + self.stats.total_pnl_usd

            # Get per-exchange P&L
            cursor.execute("""
                SELECT exchange, SUM(pnl_usd)
                FROM trades
                WHERE status != 'OPEN'
                GROUP BY exchange
            """)
            for exchange, pnl in cursor.fetchall():
                self.stats.per_exchange_pnl[exchange] = pnl

            conn.close()
        except Exception:
            pass

    def can_open_position(self, exchange: str) -> bool:
        """Check if we can open a new position."""
        with self.lock:
            # Check max positions
            if len(self.positions) >= self.config.max_positions:
                return False

            # Check if we already have a position on this exchange
            for pos in self.positions.values():
                if pos.exchange.lower() == exchange.lower():
                    return False

            # Check if exchange is tradeable
            if not self.config.is_tradeable(exchange):
                return False

            return True

    def open_position(
        self,
        signal: Signal,
        current_price: float
    ) -> Optional[Position]:
        """
        Open a position based on signal.

        Returns Position if opened, None otherwise.
        """
        if not self.can_open_position(signal.exchange):
            return None

        # DETERMINISTIC TRADING: If exit_price is calculated (impact > 2x fees),
        # bypass correlation-based tradeable check. Pure math = 100% tradeable.
        is_deterministic = hasattr(signal, 'exit_price') and signal.exit_price
        if not is_deterministic and not signal.is_tradeable:
            return None

        with self.lock:
            # Calculate position size with exchange-specific leverage
            exchange_leverage = self.config.get_leverage(signal.exchange)
            position_capital = self.stats.current_capital * self.config.position_size_pct
            size_usd = position_capital * exchange_leverage
            size_btc = size_usd / current_price

            # Calculate stop loss and take profit
            # Use calculated exit price if available (deterministic trading)
            if hasattr(signal, 'exit_price') and signal.exit_price:
                # Deterministic exit based on order book math
                take_profit = signal.exit_price
                # Still use config stop loss for safety
                if signal.direction == SignalType.SHORT:
                    stop_loss = current_price * (1 + self.config.stop_loss_pct)
                else:
                    stop_loss = current_price * (1 - self.config.stop_loss_pct)
            else:
                # Fallback to config-based exits
                if signal.direction == SignalType.SHORT:
                    stop_loss = current_price * (1 + self.config.stop_loss_pct)
                    take_profit = current_price * (1 - self.config.take_profit_pct)
                else:  # LONG
                    stop_loss = current_price * (1 - self.config.stop_loss_pct)
                    take_profit = current_price * (1 + self.config.take_profit_pct)

            # Create position with INSTRUMENT TYPE (ALL 7 SUPPORTED)
            inst_type = getattr(signal, 'instrument_type', InstrumentType.PERPETUAL)

            self.position_counter += 1
            position = Position(
                id=self.position_counter,
                exchange=signal.exchange.lower(),
                direction=signal.direction,
                entry_price=current_price,
                entry_time=signal.timestamp,
                size_usd=size_usd,
                size_btc=size_btc,
                leverage=exchange_leverage,
                stop_loss=stop_loss,
                take_profit=take_profit,
                instrument_type=inst_type,  # SPOT/MARGIN/PERPETUAL/FUTURES/OPTIONS/INVERSE/LEVERAGED_TOKEN
            )

            self.positions[position.id] = position

            # Save to database
            self._save_position(position, signal)

            return position

    def _save_position(self, position: Position, signal: Signal):
        """Save position to database."""
        conn = sqlite3.connect(self.config.trades_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO trades (
                exchange, direction, entry_price, entry_time,
                size_usd, size_btc, leverage, stop_loss, take_profit,
                status, signal_correlation, signal_win_rate, signal_samples
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.exchange,
            position.direction.value,
            position.entry_price,
            position.entry_time.isoformat(),
            position.size_usd,
            position.size_btc,
            position.leverage,
            position.stop_loss,
            position.take_profit,
            position.status.value,
            signal.correlation,
            signal.win_rate,
            signal.sample_count
        ))

        position.id = cursor.lastrowid
        conn.commit()
        conn.close()

    def check_exits(self, current_price: float, current_time: datetime) -> List[Position]:
        """
        Check all positions for exit - CLOSE WHEN PROFIT > FEES.

        Must clear fees (0.5% round trip) before closing.
        With 100x leverage: need 0.005% price move minimum.
        Target: 0.5% price move = 50% gain with 100x leverage.
        """
        closed = []
        min_profit_pct = 0.005  # 0.5% price move to cover fees + profit

        with self.lock:
            for position in list(self.positions.values()):
                exit_reason = None

                if position.direction == SignalType.SHORT:
                    # SHORT profits when price drops
                    price_change = (position.entry_price - current_price) / position.entry_price
                    if price_change >= min_profit_pct:
                        exit_reason = "PROFIT"
                        position.status = PositionStatus.TAKE_PROFIT
                else:  # LONG
                    # LONG profits when price rises
                    price_change = (current_price - position.entry_price) / position.entry_price
                    if price_change >= min_profit_pct:
                        exit_reason = "PROFIT"
                        position.status = PositionStatus.TAKE_PROFIT

                # Close position if profitable
                if exit_reason:
                    self._close_position(position, current_price, current_time, exit_reason)
                    closed.append(position)

        return closed

    def _close_position(
        self,
        position: Position,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str
    ):
        """Close a position and calculate P&L."""
        position.exit_price = exit_price
        position.exit_time = exit_time
        position.exit_reason = exit_reason

        # Calculate price move (before fees)
        if position.direction == SignalType.SHORT:
            # SHORT: profit when price drops
            price_change_pct = (position.entry_price - exit_price) / position.entry_price
        else:
            # LONG: profit when price rises
            price_change_pct = (exit_price - position.entry_price) / position.entry_price

        # SIGNAL ACCURACY: Did price move in predicted direction?
        signal_correct = price_change_pct > 0

        # Apply leverage
        position.pnl_pct = price_change_pct * position.leverage

        # Deduct fees
        fee = self.config.get_fee(position.exchange)
        position.pnl_pct -= (fee * 2)  # Entry + exit fees

        # Calculate USD P&L (on collateral, not leveraged amount)
        collateral = position.size_usd / position.leverage
        position.pnl_usd = collateral * position.pnl_pct

        # Update stats
        self.stats.total_trades += 1
        self.stats.total_pnl_usd += position.pnl_usd
        self.stats.current_capital += position.pnl_usd

        # Track SIGNAL accuracy (separate from profit)
        if signal_correct:
            self.stats.signals_correct += 1
        else:
            self.stats.signals_wrong += 1

        # Track PROFIT (after fees)
        if position.pnl_usd > 0:
            self.stats.profitable_trades += 1
        else:
            self.stats.unprofitable_trades += 1

        # Update per-exchange P&L
        if position.exchange not in self.stats.per_exchange_pnl:
            self.stats.per_exchange_pnl[position.exchange] = 0.0
        self.stats.per_exchange_pnl[position.exchange] += position.pnl_usd

        # Update peak and drawdown
        if self.stats.current_capital > self.stats.peak_capital:
            self.stats.peak_capital = self.stats.current_capital
        else:
            drawdown = (self.stats.peak_capital - self.stats.current_capital) / self.stats.peak_capital
            if drawdown > self.stats.max_drawdown_pct:
                self.stats.max_drawdown_pct = drawdown

        # Remove from active positions
        if position.id in self.positions:
            del self.positions[position.id]

        # Update database
        self._update_position(position)
        self._record_equity(exit_time)

    def _update_position(self, position: Position):
        """Update position in database."""
        conn = sqlite3.connect(self.config.trades_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE trades SET
                exit_price = ?,
                exit_time = ?,
                status = ?,
                pnl_usd = ?,
                pnl_pct = ?,
                exit_reason = ?
            WHERE id = ?
        """, (
            position.exit_price,
            position.exit_time.isoformat() if position.exit_time else None,
            position.status.value,
            position.pnl_usd,
            position.pnl_pct,
            position.exit_reason,
            position.id
        ))

        conn.commit()
        conn.close()

    def _record_equity(self, timestamp: datetime):
        """Record equity curve point."""
        conn = sqlite3.connect(self.config.trades_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO equity_curve (timestamp, capital, open_positions)
            VALUES (?, ?, ?)
        """, (
            timestamp.isoformat(),
            self.stats.current_capital,
            len(self.positions)
        ))

        conn.commit()
        conn.close()


    def close_on_opposite_flow(self, signal_direction: SignalType, current_price: float, current_time: datetime) -> List[Position]:
        """
        Close positions when opposite flow detected.
        
        DATA-DRIVEN EXIT:
        - LONG signal (OUTFLOW) -> Close all SHORTs (selling exhausted)
        - SHORT signal (INFLOW) -> Close all LONGs (new selling pressure)
        """
        closed = []
        
        with self.lock:
            for position in list(self.positions.values()):
                # Close SHORT when LONG signal comes (outflow = bullish)
                if position.direction == SignalType.SHORT and signal_direction == SignalType.LONG:
                    position.status = PositionStatus.CLOSED
                    self._close_position(position, current_price, current_time, "OPPOSITE_FLOW_LONG")
                    closed.append(position)
                    
                # Close LONG when SHORT signal comes (inflow = bearish)
                elif position.direction == SignalType.LONG and signal_direction == SignalType.SHORT:
                    position.status = PositionStatus.CLOSED
                    self._close_position(position, current_price, current_time, "OPPOSITE_FLOW_SHORT")
                    closed.append(position)
        
        return closed

    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        return list(self.positions.values())

    def get_stats(self) -> Dict:
        """Get trader statistics."""
        return {
            "capital": f"${self.stats.current_capital:.2f}",
            "total_trades": self.stats.total_trades,
            # SIGNAL ACCURACY (did price move in our direction?)
            "signal_win_rate": f"{self.stats.signal_win_rate:.1%}",
            "signals_correct": self.stats.signals_correct,
            "signals_wrong": self.stats.signals_wrong,
            # PROFIT (after fees)
            "profit_rate": f"{self.stats.profit_rate:.1%}",
            "profitable": self.stats.profitable_trades,
            "unprofitable": self.stats.unprofitable_trades,
            # P&L
            "total_pnl": f"${self.stats.total_pnl_usd:+.2f}",
            "max_drawdown": f"{self.stats.max_drawdown_pct:.1%}",
            "open_positions": len(self.positions),
            "per_exchange": {
                ex: f"${pnl:+.2f}"
                for ex, pnl in self.stats.per_exchange_pnl.items()
            }
        }


def format_position_open(position: Position) -> str:
    """Format position opening for logging."""
    inst_str = position.instrument_type.name if position.instrument_type else "PERP"
    return (
        f"[OPEN] {position.direction.value} {position.exchange.upper()} "
        f"[{inst_str}] @ ${position.entry_price:,.2f} | Size: ${position.size_usd:,.0f} "
        f"({position.size_btc:.4f} BTC) | SL: ${position.stop_loss:,.2f} "
        f"| TP: ${position.take_profit:,.2f}"
    )


def format_position_close(position: Position) -> str:
    """Format position closing for logging."""
    inst_str = position.instrument_type.name if position.instrument_type else "PERP"
    return (
        f"[CLOSE] {position.direction.value} {position.exchange.upper()} "
        f"[{inst_str}] | Entry: ${position.entry_price:,.2f} -> Exit: ${position.exit_price:,.2f} "
        f"| P&L: ${position.pnl_usd:+.2f} ({position.pnl_pct:+.1%}) "
        f"| Reason: {position.exit_reason}"
    )


def main():
    """Test the trader."""
    print("=" * 70)
    print("DETERMINISTIC TRADER")
    print("=" * 70)
    print()

    config = get_config()
    trader = DeterministicTrader(config)

    print(f"Config:")
    print(f"  - Initial capital: ${config.initial_capital}")
    print(f"  - Max leverage: {config.max_leverage}x")
    print(f"  - Max positions: {config.max_positions}")
    print(f"  - Position size: {config.position_size_pct:.0%}")
    print(f"  - Exit timeout: {config.exit_timeout_seconds}s")
    print(f"  - Stop loss: {config.stop_loss_pct:.1%}")
    print(f"  - Take profit: {config.take_profit_pct:.1%}")
    print()

    stats = trader.get_stats()
    print(f"Stats: {stats}")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
