#!/usr/bin/env python3
"""
Sovereign Trader - Entry Point
==============================

Usage:
    python run.py --mode paper   # Paper trading (simulated)
    python run.py --mode live    # Live trading (real money)

Architecture:
    Gold-standard design based on NautilusTrader + LMAX Disruptor.
    C++ core for 700ns latency, Python for strategy logic.

Philosophy:
    impact > 2x fees = TRADE
    No guessing. Just math. Let the data speak.
"""

import argparse
import logging
import sys
import signal

from sovereign_trader.core.kernel import TradingKernel, TradingMode, create_kernel
from sovereign_trader.core.config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("sovereign")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sovereign Trader - Gold-Standard Trading System"
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode: paper (simulated) or live (real money)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Print banner
    print("=" * 60)
    print("  SOVEREIGN TRADER")
    print("  Gold-Standard Architecture")
    print("=" * 60)
    print(f"  Mode:       {args.mode.upper()}")
    print(f"  Philosophy: impact > 2x fees = TRADE")
    print("=" * 60)
    print()

    # Create kernel
    kernel = create_kernel(mode=args.mode)

    # Handle shutdown gracefully
    def shutdown(signum, frame):
        logger.info("Shutdown signal received")
        kernel.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start kernel
    kernel.start()

    # Get config
    config = get_config()
    logger.info(f"Exchanges: {len(config.exchanges)}")
    logger.info(f"Min flow: {config.min_flow_btc} BTC")
    logger.info(f"Fee threshold: impact > {config.min_impact_multiple}x fees")

    if args.mode == "live":
        logger.warning("=" * 40)
        logger.warning("  LIVE MODE - REAL MONEY ENABLED")
        logger.warning("=" * 40)
    else:
        logger.info("Paper mode - no real orders")

    try:
        # Main loop would go here
        logger.info("Kernel running. Press Ctrl+C to stop.")

        # For now, just wait
        import time
        while kernel.is_running:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        kernel.stop()
        kernel.dispose()

    print()
    print("=" * 60)
    print("  SESSION COMPLETE")
    print(f"  Uptime: {kernel.uptime_seconds:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
