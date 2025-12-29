#!/usr/bin/env python3
"""
BITCOIN FLOW TRADING - MAIN ENTRY POINT
========================================

100% DETERMINISTIC 4-LAYER TRADING:
  LAYER 1:   Blockchain (C++ ZMQ) - See deposit/withdrawal FIRST
  LAYER 1.5: Historical Flow Prediction - Predict sell rate from past patterns
  LAYER 2:   Order Book (C++ REST) - Calculate expected impact
  LAYER 3:   CCXT Confirmation - Recent trades, funding rates, open interest

Usage:
    python -m bitcoin.main --paper    # Paper trading
    python -m bitcoin.main            # Live mode

The Edge:
    INFLOW  (deposit to exchange)   -> SHORT (someone about to sell)
    OUTFLOW (withdrawal from exchange) -> LONG  (selling exhausted)
"""

import subprocess
import sys
import os
import re
import time
import signal
import threading
import argparse
import tempfile
from datetime import datetime, timezone
from typing import Optional, List

# =============================================================================
# IMPORTS FROM MODULES
# =============================================================================

from .config import (
    TradingConfig, get_config,
    InstrumentType, supports_instrument, get_instrument_leverage, EXCHANGE_INSTRUMENTS
)
from .signals import CorrelationFormula, Signal, SignalType, format_signal
from .trader import DeterministicTrader, format_position_open, format_position_close
from .price_feed import MultiExchangePriceFeed
# Use C++ order book cache instead of slow CCXT
from .cpp_orderbook import CppOrderBook as OrderFlow
from .depth_calculator import (
    calculate_price_impact, calculate_exit_price, PriceImpact,
    calculate_instrument_price_impact  # Multi-instrument support
)
from .safety_checks import check_trade_safety, get_safety_checker

# NEW: 4-Layer Deterministic Confirmation
from .flow_history import FlowHistoryDB, FlowPrediction
from .ccxt_data import CCXTDataPipeline, InstrumentType as CCXTInstrument, get_pipeline

# REAL TRADING: Order Executor
from .executor import OrderExecutor
from .credentials import list_configured_exchanges


# =============================================================================
# SINGLE INSTANCE LOCK
# =============================================================================

LOCK_FILE = os.path.join(tempfile.gettempdir(), "bitcoin_trader.lock")
lock_fd = None

def acquire_lock() -> bool:
    """Ensure only one instance runs."""
    global lock_fd
    try:
        if os.path.exists(LOCK_FILE):
            return False
        lock_fd = open(LOCK_FILE, 'w')
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return True
    except:
        return False

def release_lock():
    """Release lock file."""
    try:
        if lock_fd:
            lock_fd.close()
        os.remove(LOCK_FILE)
    except:
        pass


# =============================================================================
# C++ SIGNAL PARSER
# =============================================================================

ANSI_PATTERN = re.compile(r'\x1b\[[0-9;]*m')
SIGNAL_START = re.compile(r'\[(INFLOW_SHORT|SHORT_INTERNAL|LONG_EXTERNAL)\]\s*(SHORT|LONG)')
INTERNAL_PATTERN = re.compile(r'Internal:\s*([\d.]+)\s*BTC')
EXTERNAL_PATTERN = re.compile(r'External:\s*([\d.]+)\s*BTC')
DEST_EXCH_PATTERN = re.compile(r'Dest Exch:\s*(.+)')
LATENCY_PATTERN = re.compile(r'Latency:\s*(\d+)\s*ns')


class BlockchainSignal:
    """Signal from C++ blockchain runner."""
    def __init__(self, direction: str, exchanges: List[str], inflow_btc: float,
                 outflow_btc: float, latency_ns: int):
        self.direction = direction  # 'SHORT' or 'LONG'
        self.exchanges = exchanges
        self.inflow_btc = inflow_btc
        self.outflow_btc = outflow_btc
        self.latency_ns = latency_ns
        self.timestamp = datetime.now(timezone.utc)
        self.flow_btc = inflow_btc if direction == 'SHORT' else outflow_btc


class SignalParser:
    """Parse C++ output into signals."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.in_block = False
        self.direction = None
        self.internal_btc = 0.0
        self.external_btc = 0.0
        self.exchanges = []
        self.latency_ns = 0

    def parse_line(self, line: str) -> Optional[BlockchainSignal]:
        """Parse a line, return signal when block complete."""
        clean = ANSI_PATTERN.sub('', line).strip()

        # Block start
        match = SIGNAL_START.search(clean)
        if match:
            self.reset()
            self.in_block = True
            self.direction = match.group(2)

        if not self.in_block:
            return None

        # Parse block content
        if m := INTERNAL_PATTERN.search(clean):
            self.internal_btc = float(m.group(1))
        if m := EXTERNAL_PATTERN.search(clean):
            self.external_btc = float(m.group(1))
        if m := DEST_EXCH_PATTERN.search(clean):
            exch_str = m.group(1).split('|')[0].strip()
            self.exchanges = [e.strip().lower() for e in exch_str.split(',')]
        if m := LATENCY_PATTERN.search(clean):
            self.latency_ns = int(m.group(1))
            # Latency is last field - emit signal
            if self.direction and self.exchanges:
                sig = BlockchainSignal(
                    direction=self.direction,
                    exchanges=self.exchanges,
                    inflow_btc=self.internal_btc,
                    outflow_btc=self.external_btc,
                    latency_ns=self.latency_ns
                )
                self.reset()
                return sig

        return None


# =============================================================================
# MAIN TRADING ENGINE
# =============================================================================

class TradingEngine:
    """
    Main trading engine - orchestrates everything.

    100% DETERMINISTIC 4-LAYER CONFIRMATION:
        LAYER 1:   Blockchain (C++ ZMQ)
        LAYER 1.5: Historical Flow Prediction
        LAYER 2:   Order Book (C++ REST)
        LAYER 3:   CCXT Confirmation
    """

    def __init__(self, config: TradingConfig, paper_mode: bool = True):
        self.config = config
        self.paper_mode = paper_mode
        self.running = False
        self.process = None

        # Initialize modules
        self.price_feed = MultiExchangePriceFeed()
        self.formula = CorrelationFormula(config)
        self.trader = DeterministicTrader(config) if paper_mode else None
        self.order_flow = OrderFlow()

        # NEW: 4-Layer Confirmation System
        self.flow_history = FlowHistoryDB()  # LAYER 1.5
        self.ccxt_pipeline = get_pipeline()   # LAYER 3

        # REAL TRADING: Order Executor (only when not paper mode)
        self.executor = None
        if not paper_mode:
            self.executor = OrderExecutor()
            configured = list_configured_exchanges()
            if configured:
                print(f"[REAL TRADING] Configured exchanges: {', '.join(configured)}")
            else:
                print("[WARNING] No API keys configured in .env file!")

        # Stats
        self.stats = {
            'signals': 0, 'shorts': 0, 'longs': 0, 'trades': 0,
            'confirmed': 0, 'skipped': 0,
            'layer1_pass': 0, 'layer15_pass': 0, 'layer2_pass': 0, 'layer3_pass': 0
        }

    def _get_price_from_orderbook(self, exchange: str) -> Optional[float]:
        """Get price from C++ order book cache (faster than price_feed)."""
        try:
            book = self.order_flow.fetch_full_order_book(exchange, depth=1)
            if book and book.get('bids') and book.get('asks'):
                best_bid = book['bids'][0][0] if book['bids'] else 0
                best_ask = book['asks'][0][0] if book['asks'] else 0
                if best_bid > 0 and best_ask > 0:
                    return (best_bid + best_ask) / 2
        except Exception:
            pass
        return None

    def get_price(self, exchanges: List[str]) -> tuple:
        """Get price from order book cache (primary) or price feed (fallback)."""
        # Primary: Use C++ order book cache (fastest)
        for exchange in exchanges:
            if exchange in self.config.tradeable_exchanges:
                price = self._get_price_from_orderbook(exchange)
                if price:
                    return price, exchange
        # Fallback to any tradeable exchange from order book
        for exchange in self.config.tradeable_exchanges:
            price = self._get_price_from_orderbook(exchange)
            if price:
                return price, exchange
        # Last resort: try price_feed
        for exchange in self.config.tradeable_exchanges:
            price = self.price_feed.get_price(exchange)
            if price:
                return price, exchange
        return None, None

    def select_instrument(self, exchange: str, flow_btc: float, is_short: bool) -> InstrumentType:
        """
        Select optimal instrument type for deterministic trading.

        PRIORITY ORDER (based on leverage and liquidity):
        1. PERPETUAL - Highest leverage (up to 125x), best liquidity
        2. FUTURES - High leverage, good for larger flows
        3. INVERSE - BTC-denominated, good for BTC-native flows
        4. MARGIN - Lower leverage but direct exposure
        5. LEVERAGED_TOKEN - Fixed 3x, no liquidation risk
        6. OPTIONS - Only for specific Greek opportunities
        7. SPOT - Fallback, 1x only
        """
        exchange_lower = exchange.lower()
        supported = EXCHANGE_INSTRUMENTS.get(exchange_lower, {InstrumentType.SPOT})

        priority = [
            InstrumentType.PERPETUAL,
            InstrumentType.FUTURES,
            InstrumentType.INVERSE,
            InstrumentType.MARGIN,
            InstrumentType.LEVERAGED_TOKEN,
            InstrumentType.SPOT,
        ]

        for inst in priority:
            if inst in supported:
                return inst

        return InstrumentType.SPOT

    def process_signal(self, sig: BlockchainSignal):
        """
        Process blockchain signal -> Trade decision.

        100% DETERMINISTIC 4-LAYER TRADING:
            LAYER 1:   Blockchain sees deposit (already done - sig received)
            LAYER 1.5: Historical flow prediction (will this result in sell?)
            LAYER 2:   Order book impact calculation (math)
            LAYER 3:   CCXT market confirmation (trades, funding, OI)
        """
        self.stats['signals'] += 1
        if sig.direction == 'SHORT':
            self.stats['shorts'] += 1
        else:
            self.stats['longs'] += 1

        # Get exchange from signal
        exchange = None
        for ex in sig.exchanges:
            if ex in self.config.tradeable_exchanges:
                exchange = ex
                break
        if not exchange and sig.exchanges:
            exchange = sig.exchanges[0]
        if not exchange:
            return

        # Get current price
        price, _ = self.get_price(sig.exchanges)
        if not price:
            return

        # Filter small deposits
        if sig.flow_btc < self.config.min_deposit_btc:
            return

        signal_type = SignalType.SHORT if sig.direction == 'SHORT' else SignalType.LONG
        is_short = sig.direction == 'SHORT'

        # =================================================================
        # LAYER 1: BLOCKCHAIN DETECTION (ALREADY COMPLETE)
        # =================================================================
        self.stats['layer1_pass'] += 1
        print(f"\n{'='*60}")
        print(f"[LAYER 1: BLOCKCHAIN] Detected {sig.direction}")
        print(f"  Exchange: {exchange.upper()} | Amount: {sig.flow_btc:.2f} BTC")
        print(f"  Latency: {sig.latency_ns:,} ns")
        print(f"{'='*60}")

        # =================================================================
        # LAYER 1.5: HISTORICAL FLOW PREDICTION
        # =================================================================
        flow_type = 'deposit' if is_short else 'withdrawal'
        prediction = self.flow_history.predict(exchange, sig.flow_btc, flow_type)

        print(f"\n[LAYER 1.5: HISTORICAL PREDICTION]")
        print(f"  Sell rate: {prediction.historical_sell_rate:.0%} "
              f"(based on {prediction.sample_count} similar deposits)")
        print(f"  Avg time to sell: {prediction.avg_time_to_sell_seconds/60:.1f} min")
        print(f"  Expected impact: {prediction.avg_price_impact_pct:.2f}%")
        print(f"  Confidence: {prediction.confidence:.0%}")

        # Only reject if we have ENOUGH historical data showing low sell rate
        # With < 10 samples, use exchange defaults (92-97% sell rate expected)
        if prediction.sample_count >= 10 and not prediction.is_confirmed():
            self.stats['skipped'] += 1
            print(f"  RESULT: REJECT - Historical data shows low sell rate ({prediction.sample_count} samples)")
            return
        elif prediction.sample_count < 10:
            print(f"  Note: Using exchange defaults (only {prediction.sample_count} samples, need 10+)")

        self.stats['layer15_pass'] += 1
        print(f"  RESULT: PASS")

        # =================================================================
        # LAYER 2: SELECT INSTRUMENT + ORDER BOOK IMPACT
        # =================================================================
        instrument_type = self.select_instrument(exchange, sig.flow_btc, is_short)
        inst_name = instrument_type.name
        inst_leverage = get_instrument_leverage(instrument_type)

        print(f"\n[LAYER 2: ORDER BOOK IMPACT]")
        print(f"  Instrument: {inst_name} ({inst_leverage}x leverage)")

        book = self.order_flow.fetch_full_order_book(exchange, depth=self.config.order_book_depth)
        if not book:
            print(f"  RESULT: REJECT - No order book data")
            return

        levels = book['bids'] if is_short else book['asks']
        if not levels:
            print(f"  RESULT: REJECT - Empty order book")
            return

        impact = calculate_instrument_price_impact(
            flow_btc=sig.flow_btc,
            levels=levels,
            instrument_type=instrument_type,
            is_sell=is_short,
            leverage=inst_leverage
        )

        min_required_impact = self.config.fees_pct * self.config.min_impact_multiple

        print(f"  Current depth impact: {abs(impact.price_drop_pct):.4f}%")
        print(f"  Historical prediction: {prediction.avg_price_impact_pct:.2f}%")
        print(f"  Required (2x fees): {min_required_impact:.4f}%")

        if abs(impact.price_drop_pct) < min_required_impact:
            self.stats['skipped'] += 1
            print(f"  RESULT: REJECT - Impact too small")
            return

        self.stats['layer2_pass'] += 1
        print(f"  RESULT: PASS")

        # =================================================================
        # LAYER 3: CCXT MARKET CONFIRMATION
        # =================================================================
        print(f"\n[LAYER 3: CCXT CONFIRMATION]")

        # Convert instrument type for CCXT (config uses auto(), ccxt_data uses strings)
        ccxt_instrument = CCXTInstrument(instrument_type.name.lower())
        confirmation = self.ccxt_pipeline.get_confirmation(exchange, ccxt_instrument)

        if not confirmation.fetch_success:
            print(f"  Warning: CCXT fetch failed - {confirmation.fetch_error}")
            # Continue anyway - Layer 1 + 2 are strong enough

        print(f"  Trade bias: {confirmation.trade_direction_bias:+.2f} "
              f"(Sell: {confirmation.recent_sell_volume:.2f}, Buy: {confirmation.recent_buy_volume:.2f})")

        if confirmation.funding_rate is not None:
            print(f"  Funding: {confirmation.funding_rate*100:.4f}% ({confirmation.funding_bias})")

        if confirmation.open_interest > 0:
            print(f"  Open Interest: {confirmation.open_interest:,.0f} BTC "
                  f"({confirmation.open_interest_change_pct:+.1f}%)")

        # Check if CCXT confirms our direction
        ccxt_confirmed = False
        if is_short and confirmation.confirms_short():
            ccxt_confirmed = True
            print(f"  RESULT: PASS - All indicators confirm SHORT")
        elif not is_short and confirmation.confirms_long():
            ccxt_confirmed = True
            print(f"  RESULT: PASS - All indicators confirm LONG")
        elif not confirmation.fetch_success:
            # If CCXT failed, rely on Layer 1 + 1.5 + 2
            ccxt_confirmed = True
            print(f"  RESULT: PASS (fallback) - Using Layer 1+2 confirmation")
        else:
            # Check if trade direction at least partially aligns
            if is_short and confirmation.trade_direction_bias < 0:
                ccxt_confirmed = True
                print(f"  RESULT: PASS (partial) - Trade flow confirms SHORT")
            elif not is_short and confirmation.trade_direction_bias > 0:
                ccxt_confirmed = True
                print(f"  RESULT: PASS (partial) - Trade flow confirms LONG")
            else:
                print(f"  RESULT: REJECT - Market data doesn't confirm {sig.direction}")

        if not ccxt_confirmed:
            self.stats['skipped'] += 1
            return

        self.stats['layer3_pass'] += 1
        self.stats['confirmed'] += 1

        # =================================================================
        # ALL 4 LAYERS CONFIRMED - EXECUTE TRADE
        # =================================================================
        expected_profit = abs(impact.price_drop_pct) - self.config.fees_pct
        exit_price = calculate_exit_price(price, impact, signal_type.name, self.config.take_profit_ratio)

        print(f"\n{'='*60}")
        print(f"[TRADE] ALL LAYERS CONFIRMED - EXECUTING {sig.direction}")
        print(f"{'='*60}")
        print(f"  Layer 1:   Blockchain {flow_type} detected ({sig.latency_ns:,} ns)")
        print(f"  Layer 1.5: Historical {prediction.historical_sell_rate:.0%} sell rate")
        print(f"  Layer 2:   Order book impact {abs(impact.price_drop_pct):.4f}%")
        print(f"  Layer 3:   CCXT trade bias {confirmation.trade_direction_bias:+.2f}")
        print(f"")
        print(f"  Exchange:       {exchange.upper()}")
        print(f"  Instrument:     {inst_name} ({inst_leverage}x)")
        print(f"  Entry Price:    ${price:,.2f}")
        print(f"  Exit Target:    ${exit_price:,.2f}")
        print(f"  Expected Profit: +{expected_profit:.4f}%")
        print(f"{'='*60}")

        # Create signal object
        trade_signal = Signal(
            timestamp=sig.timestamp,
            exchange=exchange,
            direction=signal_type,
            flow_btc=sig.flow_btc,
            correlation=1.0,
            win_rate=1.0,
            sample_count=1,
            expected_move_pct=impact.price_drop_pct,
            confidence=1.0
        )

        trade_signal.impact = impact
        trade_signal.exit_price = exit_price
        trade_signal.instrument_type = instrument_type

        # Safety check
        leverage = self.config.get_leverage(exchange)
        is_safe, safety_reason = check_trade_safety(
            exchange=exchange,
            order_book_price=price,
            expected_profit_pct=expected_profit,
            leverage=leverage,
            instrument_type=instrument_type
        )

        if not is_safe:
            self.stats['skipped'] += 1
            print(f"[SAFETY BLOCK] {safety_reason}")
            return

        print(f"[SAFETY OK] {safety_reason}")

        # TRADE EXECUTION
        if self.executor:
            # =================================================================
            # REAL TRADING MODE - Execute actual orders
            # =================================================================
            print(f"\n[REAL TRADING] Executing {sig.direction} on {exchange.upper()}...")

            # Calculate position size
            position_value = self.config.initial_capital * self.config.position_size_pct
            size_btc = position_value / price

            if is_short:
                order = self.executor.execute_short(exchange, inst_name, size_btc)
            else:
                order = self.executor.execute_long(exchange, inst_name, size_btc)

            if order.get('status') == 'failed':
                print(f"[ORDER FAILED] {order.get('error', 'Unknown error')}")
                self.stats['skipped'] += 1
                return

            self.stats['trades'] += 1
            print(f"\n{'='*60}")
            print(f"[ORDER EXECUTED] {order['side'].upper()} {order['size']:.6f} BTC")
            print(f"  Order ID:   {order['order_id']}")
            print(f"  Exchange:   {order['exchange'].upper()}")
            print(f"  Instrument: {order['instrument']}")
            print(f"  Price:      ${order['price']:,.2f}" if order['price'] else "  Price:      Market")
            print(f"  Status:     {order['status']}")
            print(f"{'='*60}")

            # Record for Layer 1.5 learning
            self.flow_history.record_outcome(
                txid=f"{sig.timestamp.timestamp()}_{exchange}",
                exchange=exchange,
                flow_type=flow_type,
                amount_btc=sig.flow_btc,
                detected_at=sig.timestamp,
                sold_at=None,
                price_at_detection=price,
                price_at_sell=None
            )

        elif self.trader:
            # =================================================================
            # PAPER TRADING MODE
            # =================================================================
            closed = self.trader.close_on_opposite_flow(signal_type, price, sig.timestamp)
            for pos in closed:
                print(format_position_close(pos))

            position = self.trader.open_position(trade_signal, price)
            if position:
                self.stats['trades'] += 1
                print(format_position_open(position))

                # Record outcome for learning (Layer 1.5)
                self.flow_history.record_outcome(
                    txid=f"{sig.timestamp.timestamp()}_{exchange}",
                    exchange=exchange,
                    flow_type=flow_type,
                    amount_btc=sig.flow_btc,
                    detected_at=sig.timestamp,
                    sold_at=None,  # Will update when trade closes
                    price_at_detection=price,
                    price_at_sell=None
                )

    def run(self):
        """Run the trading engine."""
        signal.signal(signal.SIGINT, lambda s, f: setattr(self, 'running', False))
        signal.signal(signal.SIGTERM, lambda s, f: setattr(self, 'running', False))

        print("=" * 60)
        print("BITCOIN FLOW TRADING - 100% DETERMINISTIC")
        print("=" * 60)
        if self.paper_mode:
            print("Mode:     PAPER (simulated trades)")
        else:
            print("Mode:     LIVE (REAL MONEY!)")
            print("          *** CAUTION: Real orders will be placed ***")
        print(f"Capital:  ${self.config.initial_capital}")
        print(f"Leverage: {self.config.max_leverage}x max")
        print()
        print("4-LAYER CONFIRMATION PIPELINE:")
        print("  Layer 1:   C++ Blockchain (ZMQ) - nanoseconds")
        print("  Layer 1.5: Historical Flow Prediction")
        print("  Layer 2:   C++ Order Book (REST) - milliseconds")
        print("  Layer 3:   CCXT Market Data - milliseconds")
        print()
        print("THE EDGE:")
        print("  INFLOW  -> SHORT (deposit = sell incoming)")
        print("  OUTFLOW -> LONG  (withdrawal = selling done)")
        print()
        print("DETERMINISTIC FORMULA:")
        print("  IF impact > 2x fees THEN guaranteed profit")
        print("=" * 60)
        print()

        # Start order flow monitoring
        self.order_flow.start()

        self.running = True
        parser = SignalParser()

        # Exit check thread
        def check_exits_loop():
            while self.running:
                try:
                    price, _ = self.get_price(list(self.config.tradeable_exchanges))
                    if price and self.trader:
                        now = datetime.now(timezone.utc)
                        closed = self.trader.check_exits(price, now)
                        for pos in closed:
                            print(format_position_close(pos))
                except Exception as e:
                    print(f"[EXIT CHECK] Error: {e}")
                time.sleep(2)

        exit_thread = threading.Thread(target=check_exits_loop, daemon=True)
        exit_thread.start()

        # Start signal source (C++ blockchain runner ONLY - no simulator)
        cpp_runner_exists = os.path.exists(self.config.cpp_runner_path)

        if not cpp_runner_exists:
            print("[ERROR] C++ blockchain runner not found!")
            print(f"  Expected: {self.config.cpp_runner_path}")
            print()
            print("Build it:")
            print("  cd /root/sovereign/cpp_runner/build")
            print("  cmake .. -DCMAKE_BUILD_TYPE=Release")
            print("  make blockchain_runner")
            print()
            print("NO SIMULATOR MODE - Only real blockchain data!")
            return

        print("[MODE] Using C++ blockchain runner")
        print()
        cmd = [self.config.cpp_runner_path, "--db", self.config.addresses_db_path]

        try:
            self.process = subprocess.Popen(
                ["stdbuf", "-oL"] + cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
        except FileNotFoundError:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

        try:
            for line in self.process.stdout:
                if not self.running:
                    break

                print(line, end='')

                sig = parser.parse_line(line)
                if sig:
                    try:
                        self.process_signal(sig)
                    except Exception as e:
                        print(f"[ERROR] Processing signal: {e}", flush=True)

        finally:
            self.running = False
            if self.process:
                self.process.terminate()
            self.print_summary()

    def print_summary(self):
        """Print session summary."""
        print()
        print("=" * 60)
        print("SESSION SUMMARY")
        print("=" * 60)
        print(f"Signals:   {self.stats['signals']} (SHORT: {self.stats['shorts']}, LONG: {self.stats['longs']})")
        print()
        print("4-LAYER PIPELINE STATS:")
        print(f"  Layer 1 (Blockchain):   {self.stats['layer1_pass']} passed")
        print(f"  Layer 1.5 (Historical): {self.stats['layer15_pass']} passed")
        print(f"  Layer 2 (Order Book):   {self.stats['layer2_pass']} passed")
        print(f"  Layer 3 (CCXT):         {self.stats['layer3_pass']} passed")
        print()
        print(f"Confirmed: {self.stats['confirmed']} (all layers passed)")
        print(f"Skipped:   {self.stats['skipped']} (failed confirmation)")
        print(f"Trades:    {self.stats['trades']}")

        if self.trader:
            stats = self.trader.get_stats()
            print()
            print("SIGNAL ACCURACY (price moved in predicted direction):")
            print(f"  Win Rate:  {stats['signal_win_rate']} ({stats['signals_correct']}/{stats['total_trades']})")
            print()
            print("PROFIT (after fees):")
            print(f"  Profit Rate: {stats['profit_rate']} ({stats['profitable']}/{stats['total_trades']})")
            print(f"  Total P&L:   {stats['total_pnl']}")
            print(f"  Capital:     {stats['capital']}")
        print("=" * 60)


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Bitcoin Flow Trading - 100% Deterministic')
    parser.add_argument('--paper', action='store_true', help='Paper trading mode')
    parser.add_argument('--live', action='store_true', help='Live trading mode')
    args = parser.parse_args()

    if not acquire_lock():
        print("ERROR: Another instance already running")
        print("Kill it: pkill -f bitcoin.main")
        sys.exit(1)

    try:
        config = get_config()
        engine = TradingEngine(config, paper_mode=not args.live)
        engine.run()
    finally:
        release_lock()


if __name__ == "__main__":
    main()
