#!/usr/bin/env python3
"""
CORRELATION-BASED TRADING FORMULA
==================================

Mathematical approach to trading signals.

THE PRINCIPLE:
- No arbitrary thresholds
- Let data speak through statistical correlation
- Only trade patterns with proven accuracy

HOW IT WORKS:
1. Record ALL flows (no minimum)
2. Track price at T+0, T+1min, T+5min, T+10min
3. Calculate correlation per (exchange, direction, size_bucket)
4. Only trade when:
   - Correlation > 0.7 (strong relationship)
   - Sample size >= 10 (statistically significant)
   - Win rate >= 90% (near-deterministic)
5. Continuously learn and adapt
"""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
from enum import Enum
import statistics
import math

from .config import TradingConfig, get_config


class SignalType(Enum):
    """Signal types."""
    SHORT = "SHORT"
    LONG = "LONG"
    HOLD = "HOLD"  # Not enough confidence


@dataclass
class CorrelationPattern:
    """A trading pattern with its statistics."""
    exchange: str
    direction: str  # "INFLOW" or "OUTFLOW"
    bucket: Tuple[float, float]  # (min_btc, max_btc)
    sample_count: int
    correlation: float  # Pearson correlation coefficient
    win_rate: float  # % of times price moved in expected direction
    avg_price_change: float  # Average price change after flow
    enabled: bool  # Whether this pattern is tradeable


@dataclass
class Signal:
    """Trading signal with mathematical confidence."""
    timestamp: datetime
    exchange: str
    direction: SignalType
    flow_btc: float
    correlation: float
    win_rate: float
    sample_count: int
    expected_move_pct: float
    confidence: float  # Combined score

    @property
    def is_tradeable(self) -> bool:
        """Check if signal meets trading criteria."""
        config = get_config()
        return (
            self.correlation >= config.min_correlation and
            self.win_rate >= config.min_win_rate and
            self.sample_count >= config.min_sample_size
        )


class CorrelationFormula:
    """
    Mathematical correlation-based signal generator.

    Records all flows, tracks price impact, calculates correlation
    per pattern, and only generates signals for proven patterns.
    """

    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or get_config()
        self.lock = threading.Lock()

        # Pattern statistics
        # Key: (exchange, direction, bucket)
        # Value: CorrelationPattern
        self.patterns: Dict[Tuple, CorrelationPattern] = {}

        # Pending price checks
        # Key: flow_id
        # Value: (timestamp, exchange, direction, flow_btc, price_at_t0)
        self.pending_checks: Dict[int, Tuple] = {}

        # Statistics
        self.total_flows = 0
        self.signals_generated = 0
        self.signals_traded = 0

        # Initialize database
        self._init_db()

        # Load historical patterns
        self._load_patterns()

        # Restore pending flows from database (survives restarts)
        self._load_pending_flows()

    def _init_db(self):
        """Initialize correlation database with extended schema."""
        conn = sqlite3.connect(self.config.correlation_db_path)
        cursor = conn.cursor()

        # Flows table - record ALL flows
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                exchange TEXT NOT NULL,
                direction TEXT NOT NULL,
                flow_btc REAL NOT NULL,
                bucket_min REAL NOT NULL,
                bucket_max REAL NOT NULL,
                price_t0 REAL,
                price_t1m REAL,
                price_t5m REAL,
                price_t10m REAL,
                price_change_1m REAL,
                price_change_5m REAL,
                price_change_10m REAL,
                verified INTEGER DEFAULT 0,
                won INTEGER
            )
        """)

        # Patterns table - aggregated statistics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                direction TEXT NOT NULL,
                bucket_min REAL NOT NULL,
                bucket_max REAL NOT NULL,
                sample_count INTEGER DEFAULT 0,
                correlation REAL DEFAULT 0.0,
                win_rate REAL DEFAULT 0.0,
                avg_price_change REAL DEFAULT 0.0,
                enabled INTEGER DEFAULT 0,
                last_updated TEXT,
                UNIQUE(exchange, direction, bucket_min, bucket_max)
            )
        """)

        # Index for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_flows_exchange_direction
            ON flows(exchange, direction)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_flows_pending
            ON flows(verified) WHERE verified = 0
        """)

        conn.commit()
        conn.close()

    def _load_patterns(self):
        """Load pattern statistics from database."""
        try:
            conn = sqlite3.connect(self.config.correlation_db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT exchange, direction, bucket_min, bucket_max,
                       sample_count, correlation, win_rate, avg_price_change, enabled
                FROM patterns
            """)

            for row in cursor.fetchall():
                exchange, direction, bucket_min, bucket_max, \
                    sample_count, correlation, win_rate, avg_price_change, enabled = row

                key = (exchange, direction, (bucket_min, bucket_max))
                self.patterns[key] = CorrelationPattern(
                    exchange=exchange,
                    direction=direction,
                    bucket=(bucket_min, bucket_max),
                    sample_count=sample_count,
                    correlation=correlation,
                    win_rate=win_rate,
                    avg_price_change=avg_price_change,
                    enabled=bool(enabled)
                )

            conn.close()
        except Exception as e:
            # No historical data yet
            pass

    def get_pattern_stats(self, exchange: str, direction: str, bucket: tuple) -> Optional[dict]:
        """
        Get pattern statistics from correlation.db.

        Returns dict with sample_count, correlation, win_rate, avg_price_change
        or None if pattern doesn't exist.
        """
        try:
            conn = sqlite3.connect(self.config.correlation_db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT sample_count, correlation, win_rate, avg_price_change
                FROM patterns
                WHERE exchange = ? AND direction = ?
                      AND bucket_min = ? AND bucket_max = ?
            """, (exchange.lower(), direction.upper(), bucket[0], bucket[1]))

            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    'sample_count': row[0],
                    'correlation': row[1],
                    'win_rate': row[2],
                    'avg_price_change': row[3]
                }
            return None
        except Exception:
            return None

    def _load_pending_flows(self):
        """
        Reload unverified flows from database into pending_checks.

        This ensures flows aren't orphaned when pipeline restarts.
        Only loads flows less than 15 minutes old that haven't been fully verified.
        """
        try:
            conn = sqlite3.connect(self.config.correlation_db_path)
            cursor = conn.cursor()

            # Get unverified flows from last 15 minutes
            cursor.execute("""
                SELECT id, timestamp, exchange, direction, flow_btc, price_t0,
                       price_t1m IS NOT NULL as t1m_done,
                       price_t5m IS NOT NULL as t5m_done
                FROM flows
                WHERE verified = 0
                  AND datetime(timestamp) > datetime('now', '-15 minutes')
            """)

            loaded = 0
            for row in cursor.fetchall():
                flow_id, ts_str, exchange, direction, flow_btc, price_t0, t1m_done, t5m_done = row

                # Parse timestamp
                try:
                    timestamp = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                # Skip if already in pending_checks
                if flow_id in self.pending_checks:
                    continue

                # Add to pending_checks with checkpoint status
                self.pending_checks[flow_id] = (
                    timestamp, exchange, direction, flow_btc, price_t0,
                    bool(t1m_done), bool(t5m_done)
                )
                loaded += 1

            conn.close()

            if loaded > 0:
                print(f"[STARTUP] Loaded {loaded} pending flows from database")

        except Exception as e:
            print(f"[STARTUP] Failed to load pending flows: {e}")

    def record_flow(
        self,
        timestamp: datetime,
        exchange: str,
        direction: str,
        flow_btc: float,
        current_price: float
    ) -> Optional[Signal]:
        """
        Record a flow and generate signal if pattern is proven.

        Returns Signal if pattern is tradeable, None otherwise.
        """
        with self.lock:
            self.total_flows += 1

            # Get bucket for this flow size
            bucket = self.config.get_bucket(flow_btc)

            # Record in database
            flow_id = self._save_flow(
                timestamp, exchange, direction, flow_btc, bucket, current_price
            )

            # Check if we have a proven pattern for this
            key = (exchange.lower(), direction.upper(), bucket)
            pattern = self.patterns.get(key)

            # DEBUG: Log pattern lookup
            if flow_btc >= 10:  # Only log significant flows
                print(f"[DEBUG] Flow: {exchange} {direction} {flow_btc:.2f} BTC -> bucket {bucket}")
                print(f"[DEBUG] Lookup key: {key}")
                print(f"[DEBUG] Pattern found: {pattern is not None}")
                if pattern:
                    print(f"[DEBUG] Pattern enabled: {pattern.enabled}, samples: {pattern.sample_count}, win_rate: {pattern.win_rate}")

            if pattern and pattern.enabled:
                # Generate signal
                signal = self._generate_signal(
                    timestamp, exchange, direction, flow_btc, pattern, current_price
                )

                # DEBUG: Log signal generation
                print(f"[DEBUG] Signal generated: {signal is not None}")
                if signal:
                    print(f"[DEBUG] Signal is_tradeable: {signal.is_tradeable}")
                    print(f"[DEBUG] Signal: corr={signal.correlation}, win={signal.win_rate}, samples={signal.sample_count}")

                if signal and signal.is_tradeable:
                    self.signals_generated += 1
                    return signal

            return None

    def _save_flow(
        self,
        timestamp: datetime,
        exchange: str,
        direction: str,
        flow_btc: float,
        bucket: Tuple[float, float],
        price: float
    ) -> int:
        """Save flow to database and return flow_id."""
        conn = sqlite3.connect(self.config.correlation_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO flows (
                timestamp, exchange, direction, flow_btc,
                bucket_min, bucket_max, price_t0
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp.isoformat(),
            exchange.lower(),
            direction.upper(),
            flow_btc,
            bucket[0],
            bucket[1],
            price
        ))

        flow_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Schedule price checks
        self.pending_checks[flow_id] = (
            timestamp, exchange, direction, flow_btc, price
        )

        return flow_id

    def _generate_signal(
        self,
        timestamp: datetime,
        exchange: str,
        direction: str,
        flow_btc: float,
        pattern: CorrelationPattern,
        current_price: float
    ) -> Signal:
        """Generate trading signal from pattern."""
        # Determine signal direction
        if direction.upper() == "INFLOW":
            # Inflow to exchange = selling pressure = SHORT
            signal_dir = SignalType.SHORT
        else:
            # Outflow from exchange = buying completed = LONG
            signal_dir = SignalType.LONG

        # Calculate confidence score
        # Combine correlation, win rate, and sample size
        confidence = (
            pattern.correlation * 0.4 +
            pattern.win_rate * 0.4 +
            min(pattern.sample_count / 100, 1.0) * 0.2
        )

        return Signal(
            timestamp=timestamp,
            exchange=exchange,
            direction=signal_dir,
            flow_btc=flow_btc,
            correlation=pattern.correlation,
            win_rate=pattern.win_rate,
            sample_count=pattern.sample_count,
            expected_move_pct=pattern.avg_price_change,
            confidence=confidence
        )

    def verify_prices(self, current_price: float, current_time: datetime):
        """
        Verify prices for pending flows.

        Should be called periodically (every 10-30 seconds).
        Uses wider windows to ensure we capture all checkpoints.
        """
        with self.lock:
            to_remove = []

            for flow_id, data in list(self.pending_checks.items()):
                timestamp, exchange, direction, flow_btc, price_t0 = data[:5]

                # Track which checkpoints we've captured
                # Data tuple: (timestamp, exchange, direction, flow_btc, price_t0, t1m_done, t5m_done)
                t1m_done = data[5] if len(data) > 5 else False
                t5m_done = data[6] if len(data) > 6 else False

                age_seconds = (current_time - timestamp).total_seconds()

                # Check 1-minute price (45-120 seconds - wide window)
                if age_seconds >= 45 and not t1m_done:
                    self._update_price(flow_id, 'price_t1m', current_price, price_t0)
                    # Update tuple to mark T+1m as done
                    self.pending_checks[flow_id] = (
                        timestamp, exchange, direction, flow_btc, price_t0, True, t5m_done
                    )
                    t1m_done = True

                # Check 5-minute price (285-360 seconds - wide window)
                if age_seconds >= 285 and not t5m_done and t1m_done:
                    self._update_price(flow_id, 'price_t5m', current_price, price_t0)
                    # Update tuple to mark T+5m as done
                    self.pending_checks[flow_id] = (
                        timestamp, exchange, direction, flow_btc, price_t0, True, True
                    )
                    t5m_done = True

                # Check 10-minute price and finalize (585+ seconds)
                if age_seconds >= 585 and t1m_done and t5m_done:
                    self._update_price(flow_id, 'price_t10m', current_price, price_t0)
                    self._finalize_flow(flow_id, exchange, direction, flow_btc)
                    to_remove.append(flow_id)

                # Cleanup old entries (> 15 minutes) - force finalize
                elif age_seconds > 900:
                    if t1m_done and t5m_done:
                        self._finalize_flow(flow_id, exchange, direction, flow_btc)
                    to_remove.append(flow_id)

            for flow_id in to_remove:
                if flow_id in self.pending_checks:
                    del self.pending_checks[flow_id]

    def _update_price(
        self,
        flow_id: int,
        column: str,
        current_price: float,
        price_t0: float
    ):
        """Update price column for a flow."""
        conn = sqlite3.connect(self.config.correlation_db_path)
        cursor = conn.cursor()

        # Calculate price change
        if price_t0 > 0:
            price_change = (current_price - price_t0) / price_t0
        else:
            price_change = 0

        # Convert price_t1m -> price_change_1m, price_t5m -> price_change_5m, etc.
        change_column = column.replace('price_t', 'price_change_')

        cursor.execute(f"""
            UPDATE flows SET {column} = ?, {change_column} = ?
            WHERE id = ?
        """, (current_price, price_change, flow_id))

        conn.commit()
        conn.close()

    def _finalize_flow(
        self,
        flow_id: int,
        exchange: str,
        direction: str,
        flow_btc: float
    ):
        """Finalize flow verification and update pattern statistics."""
        conn = sqlite3.connect(self.config.correlation_db_path)
        cursor = conn.cursor()

        # Get the flow data
        cursor.execute("""
            SELECT price_t0, price_t5m, price_change_5m
            FROM flows WHERE id = ?
        """, (flow_id,))

        row = cursor.fetchone()
        if not row:
            conn.close()
            return

        price_t0, price_t5m, price_change_5m = row

        if price_change_5m is None:
            conn.close()
            return

        # Determine if signal would have won
        # INFLOW -> expect SHORT -> price should drop (negative change)
        # OUTFLOW -> expect LONG -> price should rise (positive change)
        if direction.upper() == "INFLOW":
            won = price_change_5m < 0  # Price dropped = SHORT won
        else:
            won = price_change_5m > 0  # Price rose = LONG won

        # Mark as verified
        cursor.execute("""
            UPDATE flows SET verified = 1, won = ? WHERE id = ?
        """, (1 if won else 0, flow_id))

        conn.commit()
        conn.close()

        # Update pattern statistics
        self._update_pattern_stats(exchange, direction, flow_btc)

    def _update_pattern_stats(
        self,
        exchange: str,
        direction: str,
        flow_btc: float
    ):
        """Recalculate pattern statistics."""
        bucket = self.config.get_bucket(flow_btc)

        conn = sqlite3.connect(self.config.correlation_db_path)
        cursor = conn.cursor()

        # Get all verified flows for this pattern
        cursor.execute("""
            SELECT flow_btc, price_change_5m, won
            FROM flows
            WHERE exchange = ? AND direction = ?
                  AND bucket_min = ? AND bucket_max = ?
                  AND verified = 1
        """, (exchange.lower(), direction.upper(), bucket[0], bucket[1]))

        rows = cursor.fetchall()

        if len(rows) < self.config.min_sample_size:
            conn.close()
            return

        # Calculate statistics
        flows = [r[0] for r in rows]
        changes = [r[1] for r in rows if r[1] is not None]
        wins = sum(1 for r in rows if r[2] == 1)

        sample_count = len(rows)
        win_rate = wins / sample_count if sample_count > 0 else 0
        avg_change = statistics.mean(changes) if changes else 0

        # Calculate Pearson correlation coefficient
        correlation = 0.0
        if len(flows) >= 2 and len(changes) >= 2 and len(flows) == len(changes):
            try:
                mean_flow = statistics.mean(flows)
                mean_change = statistics.mean(changes)

                numerator = sum((f - mean_flow) * (c - mean_change)
                               for f, c in zip(flows, changes))

                flow_var = sum((f - mean_flow) ** 2 for f in flows)
                change_var = sum((c - mean_change) ** 2 for c in changes)

                denominator = math.sqrt(flow_var * change_var)

                if denominator > 0:
                    correlation = numerator / denominator
            except Exception:
                correlation = 0.0

        # Determine if pattern should be enabled
        enabled = (
            sample_count >= self.config.min_sample_size and
            abs(correlation) >= self.config.min_correlation and
            win_rate >= self.config.min_win_rate
        )

        # Update patterns table
        cursor.execute("""
            INSERT INTO patterns (
                exchange, direction, bucket_min, bucket_max,
                sample_count, correlation, win_rate, avg_price_change,
                enabled, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, direction, bucket_min, bucket_max)
            DO UPDATE SET
                sample_count = excluded.sample_count,
                correlation = excluded.correlation,
                win_rate = excluded.win_rate,
                avg_price_change = excluded.avg_price_change,
                enabled = excluded.enabled,
                last_updated = excluded.last_updated
        """, (
            exchange.lower(),
            direction.upper(),
            bucket[0],
            bucket[1],
            sample_count,
            correlation,
            win_rate,
            avg_change,
            1 if enabled else 0,
            datetime.now(timezone.utc).isoformat()
        ))

        conn.commit()
        conn.close()

        # Update in-memory pattern
        key = (exchange.lower(), direction.upper(), bucket)
        self.patterns[key] = CorrelationPattern(
            exchange=exchange.lower(),
            direction=direction.upper(),
            bucket=bucket,
            sample_count=sample_count,
            correlation=correlation,
            win_rate=win_rate,
            avg_price_change=avg_change,
            enabled=enabled
        )

    def get_enabled_patterns(self) -> List[CorrelationPattern]:
        """Get all enabled trading patterns."""
        return [p for p in self.patterns.values() if p.enabled]

    def get_stats(self) -> Dict:
        """Get formula statistics."""
        enabled = self.get_enabled_patterns()
        return {
            "total_flows": self.total_flows,
            "signals_generated": self.signals_generated,
            "signals_traded": self.signals_traded,
            "patterns_tracked": len(self.patterns),
            "patterns_enabled": len(enabled),
            "pending_checks": len(self.pending_checks),
            "enabled_patterns": [
                {
                    "exchange": p.exchange,
                    "direction": p.direction,
                    "bucket": p.bucket,
                    "samples": p.sample_count,
                    "correlation": f"{p.correlation:.2f}",
                    "win_rate": f"{p.win_rate:.1%}"
                }
                for p in enabled
            ]
        }


def format_signal(signal: Signal) -> str:
    """Format signal for logging."""
    tradeable = "TRADEABLE" if signal.is_tradeable else "LEARNING"
    return (
        f"[{signal.timestamp.strftime('%H:%M:%S')} UTC] "
        f"{signal.direction.value} {signal.exchange.upper()} "
        f"| Flow: {signal.flow_btc:.1f} BTC "
        f"| Corr: {signal.correlation:.2f} | Win: {signal.win_rate:.0%} "
        f"| Samples: {signal.sample_count} | {tradeable}"
    )


def main():
    """Test the correlation formula."""
    print("=" * 70)
    print("CORRELATION-BASED TRADING FORMULA")
    print("=" * 70)
    print()
    print("MATHEMATICAL MODEL:")
    print()
    print("  1. Record ALL flows (no minimum threshold)")
    print("  2. Track price at T+0, T+1m, T+5m, T+10m")
    print("  3. Calculate correlation per (exchange, direction, bucket)")
    print("  4. Only trade when:")
    print("     - Correlation >= 0.7 (strong relationship)")
    print("     - Sample size >= 10 (statistically significant)")
    print("     - Win rate >= 90% (near-deterministic)")
    print("  5. Continuously learn and adapt")
    print()

    config = get_config()
    formula = CorrelationFormula(config)

    print(f"Config:")
    print(f"  - Min correlation: {config.min_correlation}")
    print(f"  - Min win rate: {config.min_win_rate}")
    print(f"  - Min samples: {config.min_sample_size}")
    print()

    stats = formula.get_stats()
    print(f"Stats: {stats}")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
