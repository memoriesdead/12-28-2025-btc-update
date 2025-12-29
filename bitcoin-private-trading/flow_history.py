"""
LAYER 1.5: Historical Flow Prediction

This bridges blockchain detection and order book confirmation.
Uses historical data to PREDICT what will happen after this deposit.

Timeline:
  T0:        Blockchain deposit detected (nanoseconds)
  T0 + 1us:  Historical confirmation (microseconds) <-- THIS LAYER
  T0 + 1ms:  Order book impact calculated (milliseconds)
  T0 + 100ms: CCXT market state confirmed (milliseconds)
  T0 + 500ms: OUR TRADE EXECUTES
  T0 + 2-15min: Their sell hits order book (WE'RE ALREADY IN POSITION!)
"""
import sqlite3
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import os


@dataclass
class FlowPrediction:
    """Historical prediction for a deposit/withdrawal."""
    exchange: str
    amount_btc: float

    # Historical patterns
    historical_sell_rate: float  # % of deposits that result in sell
    avg_time_to_sell_seconds: float  # Typical delay before sell
    avg_price_impact_pct: float  # Expected price move
    sample_count: int  # How many similar deposits we've seen

    # Confidence
    confidence: float  # 0.0 to 1.0

    def is_confirmed(self) -> bool:
        """Is this deposit highly likely to result in sell?"""
        return (
            self.historical_sell_rate >= 0.90 and  # 90%+ sell rate
            self.sample_count >= 10 and  # Enough historical data
            self.confidence >= 0.80  # High confidence
        )

    def expected_profit(self, fees_pct: float) -> float:
        """Expected profit based on historical impact."""
        return abs(self.avg_price_impact_pct) - fees_pct


class FlowHistoryDB:
    """Query historical flow patterns from correlation.db."""

    def __init__(self, db_path: str = "/root/sovereign/correlation.db"):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self):
        """Create tables if not exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS flow_outcomes (
                        id INTEGER PRIMARY KEY,
                        txid TEXT UNIQUE,
                        exchange TEXT,
                        flow_type TEXT,
                        amount_btc REAL,
                        detected_at TIMESTAMP,
                        sold_at TIMESTAMP,
                        price_at_detection REAL,
                        price_at_sell REAL,
                        actual_impact_pct REAL,
                        time_to_sell_seconds INTEGER
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_flow_exchange_amount
                    ON flow_outcomes(exchange, amount_btc)
                """)
        except Exception:
            pass  # DB may not exist yet

    def predict(self, exchange: str, amount_btc: float, flow_type: str = 'deposit') -> FlowPrediction:
        """Predict what will happen based on historical patterns."""

        if not os.path.exists(self.db_path):
            # No history yet - use conservative defaults based on known behavior
            defaults = get_exchange_default(exchange)
            return FlowPrediction(
                exchange=exchange,
                amount_btc=amount_btc,
                historical_sell_rate=defaults['sell_rate'],
                avg_time_to_sell_seconds=defaults['avg_time'],
                avg_price_impact_pct=defaults['avg_impact'],
                sample_count=0,
                confidence=0.50  # Low confidence until we have data
            )

        # Query historical deposits of similar size to this exchange
        # Range: 0.5x to 2x the current deposit amount
        min_amount = amount_btc * 0.5
        max_amount = amount_btc * 2.0

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN sold_at IS NOT NULL THEN 1 END) as sold_count,
                        AVG(CASE WHEN sold_at IS NOT NULL THEN time_to_sell_seconds END) as avg_time,
                        AVG(actual_impact_pct) as avg_impact
                    FROM flow_outcomes
                    WHERE exchange = ?
                      AND flow_type = ?
                      AND amount_btc BETWEEN ? AND ?
                      AND detected_at > datetime('now', '-30 days')
                """, (exchange.lower(), flow_type, min_amount, max_amount))

                row = cursor.fetchone()
                total, sold_count, avg_time, avg_impact = row

                if total == 0:
                    # No historical data - use exchange defaults
                    defaults = get_exchange_default(exchange)
                    return FlowPrediction(
                        exchange=exchange,
                        amount_btc=amount_btc,
                        historical_sell_rate=defaults['sell_rate'],
                        avg_time_to_sell_seconds=defaults['avg_time'],
                        avg_price_impact_pct=defaults['avg_impact'],
                        sample_count=0,
                        confidence=0.50
                    )

                sell_rate = sold_count / total if total > 0 else 0
                avg_time = avg_time or 600
                avg_impact = avg_impact or -0.10

                # Confidence based on sample size
                confidence = min(1.0, total / 50)  # Max confidence at 50 samples

                return FlowPrediction(
                    exchange=exchange,
                    amount_btc=amount_btc,
                    historical_sell_rate=sell_rate,
                    avg_time_to_sell_seconds=avg_time,
                    avg_price_impact_pct=avg_impact,
                    sample_count=total,
                    confidence=confidence
                )
        except Exception:
            # Fallback to defaults
            defaults = get_exchange_default(exchange)
            return FlowPrediction(
                exchange=exchange,
                amount_btc=amount_btc,
                historical_sell_rate=defaults['sell_rate'],
                avg_time_to_sell_seconds=defaults['avg_time'],
                avg_price_impact_pct=defaults['avg_impact'],
                sample_count=0,
                confidence=0.50
            )

    def record_outcome(self, txid: str, exchange: str, flow_type: str,
                       amount_btc: float, detected_at: datetime,
                       sold_at: Optional[datetime], price_at_detection: float,
                       price_at_sell: Optional[float]):
        """Record the actual outcome for learning."""
        try:
            actual_impact = None
            time_to_sell = None
            if sold_at and price_at_sell:
                actual_impact = (price_at_sell - price_at_detection) / price_at_detection * 100
                time_to_sell = int((sold_at - detected_at).total_seconds())

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO flow_outcomes
                    (txid, exchange, flow_type, amount_btc, detected_at,
                     sold_at, price_at_detection, price_at_sell,
                     actual_impact_pct, time_to_sell_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (txid, exchange.lower(), flow_type, amount_btc,
                      detected_at.isoformat(), sold_at.isoformat() if sold_at else None,
                      price_at_detection, price_at_sell,
                      actual_impact, time_to_sell))
        except Exception:
            pass  # Don't fail on recording errors


# Exchange-specific default patterns (based on known behavior)
EXCHANGE_DEFAULTS = {
    'binance': {'sell_rate': 0.97, 'avg_time': 480, 'avg_impact': -0.12},
    'okx': {'sell_rate': 0.96, 'avg_time': 540, 'avg_impact': -0.10},
    'bybit': {'sell_rate': 0.95, 'avg_time': 420, 'avg_impact': -0.11},
    'coinbase': {'sell_rate': 0.92, 'avg_time': 900, 'avg_impact': -0.08},
    'kraken': {'sell_rate': 0.90, 'avg_time': 720, 'avg_impact': -0.07},
    'htx': {'sell_rate': 0.94, 'avg_time': 600, 'avg_impact': -0.09},
    'gate': {'sell_rate': 0.93, 'avg_time': 660, 'avg_impact': -0.10},
    'bitget': {'sell_rate': 0.94, 'avg_time': 540, 'avg_impact': -0.09},
    'mexc': {'sell_rate': 0.95, 'avg_time': 480, 'avg_impact': -0.11},
    'kucoin': {'sell_rate': 0.93, 'avg_time': 600, 'avg_impact': -0.09},
    'deribit': {'sell_rate': 0.91, 'avg_time': 600, 'avg_impact': -0.08},
    'bitfinex': {'sell_rate': 0.92, 'avg_time': 720, 'avg_impact': -0.09},
    'phemex': {'sell_rate': 0.94, 'avg_time': 540, 'avg_impact': -0.10},
    'coinex': {'sell_rate': 0.93, 'avg_time': 600, 'avg_impact': -0.09},
    'poloniex': {'sell_rate': 0.91, 'avg_time': 660, 'avg_impact': -0.08},
    'gemini': {'sell_rate': 0.88, 'avg_time': 900, 'avg_impact': -0.06},
    'bitstamp': {'sell_rate': 0.87, 'avg_time': 960, 'avg_impact': -0.05},
}


def get_exchange_default(exchange: str) -> dict:
    """Get default prediction parameters for an exchange."""
    return EXCHANGE_DEFAULTS.get(exchange.lower(), {
        'sell_rate': 0.95,
        'avg_time': 600,
        'avg_impact': -0.10
    })
