#!/usr/bin/env python3
"""
Unified Trading Tracker - All 3 Strategies

Tracks HQT (arbitrage), SCT (statistical), and Deterministic (blockchain) trades.
Shows real-time P&L, entry/exit times, and performance metrics.

Usage:
    python unified_tracker.py           # Live dashboard
    python unified_tracker.py --once    # Single snapshot
"""

import asyncio
import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "cpp" / "python"))

try:
    from hqt_bridge import HQTBridge, ArbitrageOpportunity
    HQT_AVAILABLE = True
except ImportError:
    HQT_AVAILABLE = False
    ArbitrageOpportunity = None  # Type hint placeholder

try:
    from sct_bridge import SCTBridge, CertaintyStatus
    SCT_AVAILABLE = True
except ImportError:
    SCT_AVAILABLE = False
    CertaintyStatus = None  # Type hint placeholder

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    print("[WARN] CCXT not available")


# ============================================================================
# CONFIGURATION - PER-EXCHANGE MAX LEVERAGE
# ============================================================================

@dataclass
class TradeConfig:
    """Maximum leverage configuration - PER EXCHANGE from official docs Dec 2024."""
    position_size_pct: float = 0.10  # 10% per position
    max_positions: int = 5
    stop_loss_pct: float = 0.02    # 2% stop
    take_profit_pct: float = 0.04  # 4% take profit

    # Per-exchange max leverage (from official exchange documentation)
    exchange_leverage: Dict[str, int] = field(default_factory=lambda: {
        'mexc': 500,        # MEXC max 500x futures
        'binance': 125,     # Binance max 125x (20x new users)
        'bybit': 100,       # Bybit max 100x
        'kraken': 50,       # Kraken max 50x
        'coinbase': 10,     # Coinbase max 10x (US regulated)
        'gemini': 5,        # Gemini 5x US, 100x non-US
        'bitstamp': 10,     # Bitstamp 10x max
        'crypto.com': 20,   # Crypto.com max 20x
        'default': 10       # Conservative default
    })

    # Strategy-specific
    hqt_min_profit_usd: float = 5.0
    sct_min_certainty: float = 0.5075
    det_min_correlation: float = 0.70
    det_min_win_rate: float = 0.90

    def get_leverage(self, exchange: str) -> int:
        """Get max leverage for exchange from official docs."""
        return self.exchange_leverage.get(exchange.lower(), self.exchange_leverage['default'])


# ============================================================================
# TRADE TRACKING
# ============================================================================

@dataclass
class Trade:
    """Unified trade record."""
    id: int
    strategy: str          # "HQT", "SCT", "DET"
    direction: str         # "LONG" or "SHORT"
    entry_price: float
    entry_time: datetime
    size_usd: float
    leverage: int
    status: str            # "OPEN", "CLOSED", "STOPPED_OUT", "TIMED_OUT"
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    exchange: str = ""
    signal_info: str = ""


@dataclass
class StrategyStats:
    """Stats for a single strategy."""
    name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    open_positions: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    win_rate: float = 0.0

    def update_win_rate(self):
        closed = self.wins + self.losses
        self.win_rate = self.wins / closed if closed > 0 else 0.0


# ============================================================================
# UNIFIED TRACKER
# ============================================================================

class UnifiedTracker:
    """
    Tracks all 3 strategies in one place.

    Strategies:
    1. HQT - Arbitrage (100% win rate when spread > costs)
    2. SCT - Statistical (trades when Wilson CI >= 50.75%)
    3. DET - Deterministic (blockchain flow signals)
    """

    def __init__(self, db_path: str = "unified_trades.db"):
        self.config = TradeConfig()
        self.db_path = Path(db_path)
        self.trades: List[Trade] = []
        self.current_price: float = 0.0

        # Strategy trackers
        self.hqt = HQTBridge() if HQT_AVAILABLE else None
        self.sct = SCTBridge(min_wr=0.5075, confidence=0.99) if SCT_AVAILABLE else None

        # Exchange connections
        self.exchanges: Dict[str, any] = {}
        if CCXT_AVAILABLE:
            self._init_exchanges()

        # Initialize database
        self._init_db()

        # Load existing trades
        self._load_trades()

    def _init_exchanges(self):
        """Initialize exchange connections for price feeds."""
        exchange_ids = ['kraken', 'coinbase', 'gemini', 'bitstamp', 'binance', 'bybit']
        for ex_id in exchange_ids:
            try:
                self.exchanges[ex_id] = getattr(ccxt, ex_id)()
            except:
                pass

    def _init_db(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                size_usd REAL NOT NULL,
                leverage INTEGER NOT NULL,
                status TEXT NOT NULL,
                exit_price REAL,
                exit_time TEXT,
                pnl_usd REAL DEFAULT 0.0,
                pnl_pct REAL DEFAULT 0.0,
                exchange TEXT,
                signal_info TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hqt_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                buy_exchange TEXT NOT NULL,
                sell_exchange TEXT NOT NULL,
                buy_price REAL NOT NULL,
                sell_price REAL NOT NULL,
                spread_pct REAL NOT NULL,
                profit_usd REAL NOT NULL,
                executed INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sct_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                strategy TEXT NOT NULL,
                wins INTEGER NOT NULL,
                total INTEGER NOT NULL,
                lower_bound REAL NOT NULL,
                status TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _load_trades(self):
        """Load trades from database."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("""
            SELECT id, strategy, direction, entry_price, entry_time, size_usd,
                   leverage, status, exit_price, exit_time, pnl_usd, pnl_pct,
                   exchange, signal_info
            FROM trades ORDER BY id DESC
        """).fetchall()
        conn.close()

        for row in rows:
            self.trades.append(Trade(
                id=row[0],
                strategy=row[1],
                direction=row[2],
                entry_price=row[3],
                entry_time=datetime.fromisoformat(row[4]),
                size_usd=row[5],
                leverage=row[6],
                status=row[7],
                exit_price=row[8],
                exit_time=datetime.fromisoformat(row[9]) if row[9] else None,
                pnl_usd=row[10],
                pnl_pct=row[11],
                exchange=row[12] or "",
                signal_info=row[13] or ""
            ))

    def record_trade(self, trade: Trade) -> int:
        """Record a new trade."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            INSERT INTO trades (strategy, direction, entry_price, entry_time,
                               size_usd, leverage, status, exchange, signal_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (trade.strategy, trade.direction, trade.entry_price,
              trade.entry_time.isoformat(), trade.size_usd, trade.leverage,
              trade.status, trade.exchange, trade.signal_info))
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()

        trade.id = trade_id
        self.trades.insert(0, trade)
        return trade_id

    def close_trade(self, trade_id: int, exit_price: float, reason: str = "CLOSED"):
        """Close a trade and calculate P&L."""
        for trade in self.trades:
            if trade.id == trade_id and trade.status == "OPEN":
                trade.exit_price = exit_price
                trade.exit_time = datetime.now(timezone.utc)
                trade.status = reason

                # Calculate P&L
                if trade.direction == "LONG":
                    pnl_pct = (exit_price - trade.entry_price) / trade.entry_price
                else:  # SHORT
                    pnl_pct = (trade.entry_price - exit_price) / trade.entry_price

                trade.pnl_pct = pnl_pct * trade.leverage
                trade.pnl_usd = trade.size_usd * trade.pnl_pct

                # Update database
                conn = sqlite3.connect(self.db_path)
                conn.execute("""
                    UPDATE trades SET exit_price=?, exit_time=?, status=?,
                                     pnl_usd=?, pnl_pct=?
                    WHERE id=?
                """, (exit_price, trade.exit_time.isoformat(), reason,
                      trade.pnl_usd, trade.pnl_pct, trade_id))
                conn.commit()
                conn.close()
                break

    async def fetch_price(self) -> float:
        """Fetch current BTC price."""
        if not self.exchanges:
            return 0.0

        for name, ex in self.exchanges.items():
            try:
                ticker = ex.fetch_ticker('BTC/USDT')
                self.current_price = ticker['last']
                return self.current_price
            except:
                continue
        return 0.0

    def calculate_unrealized_pnl(self, trade: Trade) -> float:
        """Calculate unrealized P&L for open trade."""
        if trade.status != "OPEN" or self.current_price <= 0:
            return 0.0

        # Use absolute size (some old trades have negative size)
        size = abs(trade.size_usd)

        if trade.direction == "LONG":
            pnl_pct = (self.current_price - trade.entry_price) / trade.entry_price
        else:  # SHORT
            pnl_pct = (trade.entry_price - self.current_price) / trade.entry_price

        return size * pnl_pct * trade.leverage

    def get_strategy_stats(self, strategy: str) -> StrategyStats:
        """Get stats for a specific strategy."""
        stats = StrategyStats(name=strategy)

        for trade in self.trades:
            if trade.strategy != strategy:
                continue

            stats.total_trades += 1

            if trade.status == "OPEN":
                stats.open_positions += 1
                stats.unrealized_pnl += self.calculate_unrealized_pnl(trade)
            else:
                stats.realized_pnl += trade.pnl_usd
                if trade.pnl_usd > 0:
                    stats.wins += 1
                else:
                    stats.losses += 1

        stats.update_win_rate()
        return stats

    def get_all_stats(self) -> Dict[str, StrategyStats]:
        """Get stats for all strategies."""
        return {
            "HQT": self.get_strategy_stats("HQT"),
            "SCT": self.get_strategy_stats("SCT"),
            "DET": self.get_strategy_stats("DET"),
        }

    # ========================================================================
    # HQT - Arbitrage Detection
    # ========================================================================

    async def check_hqt(self):
        """Check for HQT arbitrage opportunities."""
        if not self.hqt:
            return None

        # Update prices from all exchanges
        for name, ex in self.exchanges.items():
            try:
                ob = ex.fetch_order_book('BTC/USDT', limit=1)
                if ob['bids'] and ob['asks']:
                    self.hqt.update_price(name, ob['bids'][0][0], ob['asks'][0][0])
            except:
                pass

        opp = self.hqt.find_opportunity()
        if opp and opp.profit_usd >= self.config.hqt_min_profit_usd:
            # Log opportunity
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT INTO hqt_opportunities
                (timestamp, buy_exchange, sell_exchange, buy_price, sell_price, spread_pct, profit_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(), opp.buy_exchange,
                  opp.sell_exchange, opp.buy_price, opp.sell_price,
                  opp.spread_pct, opp.profit_usd))
            conn.commit()
            conn.close()
            return opp

        return None

    # ========================================================================
    # SCT - Statistical Certainty Check
    # ========================================================================

    def check_sct(self, strategy: str, wins: int, total: int) -> bool:
        """Check if strategy meets SCT certainty threshold."""
        if not self.sct:
            return False

        result = self.sct.check(wins, total)

        # Log check
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO sct_checks (timestamp, strategy, wins, total, lower_bound, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc).isoformat(), strategy, wins, total,
              result.lower_bound, result.status.value))
        conn.commit()
        conn.close()

        return result.status == CertaintyStatus.CERTAIN

    # ========================================================================
    # DISPLAY
    # ========================================================================

    def print_dashboard(self):
        """Print unified dashboard."""
        print("\033[2J\033[H")  # Clear screen

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("=" * 80)
        print(f"  UNIFIED TRADING DASHBOARD - {now}")
        print(f"  BTC: ${self.current_price:,.2f} | Per-Exchange Leverage (Official Docs)")
        print("=" * 80)

        # Strategy summary
        stats = self.get_all_stats()
        total_realized = sum(s.realized_pnl for s in stats.values())
        total_unrealized = sum(s.unrealized_pnl for s in stats.values())

        print(f"\n{'Strategy':<12} {'Trades':>8} {'Open':>6} {'W/L':>10} {'Win%':>8} {'Realized':>12} {'Unrealized':>12}")
        print("-" * 80)

        for name, s in stats.items():
            wl = f"{s.wins}/{s.losses}"
            wr = f"{s.win_rate*100:.1f}%" if s.total_trades > 0 else "N/A"
            realized = f"${s.realized_pnl:+,.2f}"
            unrealized = f"${s.unrealized_pnl:+,.2f}"

            # Color coding
            r_color = "\033[92m" if s.realized_pnl >= 0 else "\033[91m"
            u_color = "\033[92m" if s.unrealized_pnl >= 0 else "\033[91m"
            reset = "\033[0m"

            print(f"{name:<12} {s.total_trades:>8} {s.open_positions:>6} {wl:>10} {wr:>8} "
                  f"{r_color}{realized:>12}{reset} {u_color}{unrealized:>12}{reset}")

        print("-" * 80)
        t_color = "\033[92m" if total_realized + total_unrealized >= 0 else "\033[91m"
        print(f"{'TOTAL':<12} {'':<8} {'':<6} {'':<10} {'':<8} "
              f"${total_realized:+,.2f} {t_color}${total_unrealized:+,.2f}\033[0m")

        # Open positions
        open_trades = [t for t in self.trades if t.status == "OPEN"]
        if open_trades:
            print(f"\n{'='*80}")
            print("OPEN POSITIONS")
            print(f"{'='*80}")
            print(f"{'ID':>4} {'Strategy':<6} {'Dir':<6} {'Entry':>12} {'Current':>12} {'Size':>10} {'P&L':>12}")
            print("-" * 80)

            for t in open_trades[:10]:
                unrealized = self.calculate_unrealized_pnl(t)
                pnl_color = "\033[92m" if unrealized >= 0 else "\033[91m"
                size_display = abs(t.size_usd)
                print(f"{t.id:>4} {t.strategy:<6} {t.direction:<6} "
                      f"${t.entry_price:>11,.2f} ${self.current_price:>11,.2f} "
                      f"${size_display:>9,.2f} {pnl_color}${unrealized:>+11,.2f}\033[0m")

        # Recent closed trades
        closed_trades = [t for t in self.trades if t.status != "OPEN"][:5]
        if closed_trades:
            print(f"\n{'='*80}")
            print("RECENT CLOSED TRADES")
            print(f"{'='*80}")
            print(f"{'ID':>4} {'Strategy':<6} {'Dir':<6} {'Entry':>12} {'Exit':>12} {'P&L':>12} {'Status':<12}")
            print("-" * 80)

            for t in closed_trades:
                pnl_color = "\033[92m" if t.pnl_usd >= 0 else "\033[91m"
                exit_p = f"${t.exit_price:,.2f}" if t.exit_price else "N/A"
                print(f"{t.id:>4} {t.strategy:<6} {t.direction:<6} "
                      f"${t.entry_price:>11,.2f} {exit_p:>12} "
                      f"{pnl_color}${t.pnl_usd:>+11,.2f}\033[0m {t.status:<12}")

        print(f"\n{'='*80}")
        print("  [Ctrl+C to exit]")
        print("=" * 80)

    async def run_live(self, interval: int = 5):
        """Run live dashboard with auto-refresh."""
        print("Starting unified tracker...")
        print("Per-exchange leverage limits (from official docs Dec 2024):")
        for ex, lev in sorted(self.config.exchange_leverage.items(), key=lambda x: -x[1] if x[0] != 'default' else 0):
            if ex != 'default':
                print(f"  {ex.upper()}: {lev}x")
        print(f"Position size: {self.config.position_size_pct*100:.0f}%")

        try:
            while True:
                # Fetch current price
                await self.fetch_price()

                # Check for HQT opportunities
                opp = await self.check_hqt()
                if opp:
                    print(f"\n[HQT] ARBITRAGE: Buy {opp.buy_exchange} @ ${opp.buy_price:,.2f}, "
                          f"Sell {opp.sell_exchange} @ ${opp.sell_price:,.2f}, "
                          f"Profit: ${opp.profit_usd:.2f}")

                # Display dashboard
                self.print_dashboard()

                await asyncio.sleep(interval)

        except KeyboardInterrupt:
            print("\n\nShutting down...")

    def print_summary(self):
        """Print one-time summary."""
        if self.exchanges:
            # Sync fetch price
            for name, ex in self.exchanges.items():
                try:
                    ticker = ex.fetch_ticker('BTC/USDT')
                    self.current_price = ticker['last']
                    break
                except:
                    pass

        self.print_dashboard()


# ============================================================================
# IMPORT FROM VPS TRADES
# ============================================================================

def import_vps_trades(tracker: UnifiedTracker, vps_db_path: str):
    """Import trades from VPS database."""
    try:
        conn = sqlite3.connect(vps_db_path)
        rows = conn.execute("""
            SELECT id, exchange, direction, entry_price, entry_time, size_usd,
                   leverage, status, exit_price, exit_time, pnl_usd, pnl_pct,
                   signal_correlation, signal_win_rate
            FROM trades ORDER BY id
        """).fetchall()
        conn.close()

        for row in rows:
            trade = Trade(
                id=0,  # Will be assigned
                strategy="DET",  # Deterministic blockchain signals
                direction=row[2],
                entry_price=row[3],
                entry_time=datetime.fromisoformat(row[4]),
                size_usd=row[5],
                leverage=row[6],
                status=row[7],
                exit_price=row[8],
                exit_time=datetime.fromisoformat(row[9]) if row[9] else None,
                pnl_usd=row[10] or 0.0,
                pnl_pct=row[11] or 0.0,
                exchange=row[1],
                signal_info=f"corr={row[12]}, wr={row[13]}"
            )
            tracker.record_trade(trade)

        print(f"Imported {len(rows)} trades from VPS")

    except Exception as e:
        print(f"Could not import VPS trades: {e}")


# ============================================================================
# MAIN
# ============================================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description='Unified Trading Tracker')
    parser.add_argument('--once', action='store_true', help='Single snapshot')
    parser.add_argument('--interval', type=int, default=5, help='Refresh interval')
    parser.add_argument('--db', type=str, default='unified_trades.db', help='Database path')
    parser.add_argument('--import-vps', type=str, help='Import from VPS trades.db')

    args = parser.parse_args()

    tracker = UnifiedTracker(db_path=args.db)

    if args.import_vps:
        import_vps_trades(tracker, args.import_vps)

    if args.once:
        tracker.print_summary()
    else:
        await tracker.run_live(interval=args.interval)


if __name__ == "__main__":
    asyncio.run(main())
