"""
Sovereign Trader - Trading Kernel
==================================

NautilusKernel-inspired orchestration.
Same code runs for both paper and live trading.

Reference: https://nautilustrader.io/docs/latest/concepts/architecture/
"""

from enum import Enum, auto
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
import logging
import time

from .message_bus import MessageBus, get_message_bus
from .config import TradingConfig, get_config
from ..model.events import Event, EventType

logger = logging.getLogger(__name__)


class TradingMode(Enum):
    """Trading mode."""
    PAPER = auto()  # Simulated orders
    LIVE = auto()   # Real money


class KernelState(Enum):
    """Kernel lifecycle states (matching NautilusTrader)."""
    PRE_INITIALIZED = auto()
    READY = auto()
    RUNNING = auto()
    STOPPED = auto()
    DEGRADED = auto()
    FAULTED = auto()
    DISPOSED = auto()


@dataclass
class KernelConfig:
    """Kernel configuration."""
    mode: TradingMode = TradingMode.PAPER
    config: TradingConfig = None

    def __post_init__(self):
        if self.config is None:
            self.config = get_config()


class TradingKernel:
    """
    Core trading kernel.

    Matches NautilusTrader's NautilusKernel pattern:
    - Same code for paper and live trading
    - Event-driven architecture
    - Component lifecycle management
    - MessageBus coordination

    Usage:
        kernel = TradingKernel(mode=TradingMode.PAPER)
        kernel.start()
        # ... trading loop ...
        kernel.stop()
    """

    def __init__(self, mode: TradingMode = TradingMode.PAPER,
                 config: Optional[TradingConfig] = None):
        """
        Initialize the trading kernel.

        Args:
            mode: PAPER for simulated, LIVE for real money
            config: Trading configuration (uses default if None)
        """
        self.mode = mode
        self.config = config or get_config()
        self.state = KernelState.PRE_INITIALIZED

        # Core components
        self._message_bus = get_message_bus()
        self._start_time_ns: Optional[int] = None
        self._components: Dict[str, Any] = {}

        # Stats
        self._event_count = 0
        self._signal_count = 0
        self._trade_count = 0

        logger.info(f"Kernel initialized in {mode.name} mode")

    def register_component(self, name: str, component: Any) -> None:
        """Register a component with the kernel."""
        self._components[name] = component
        logger.debug(f"Registered component: {name}")

    def get_component(self, name: str) -> Optional[Any]:
        """Get a registered component."""
        return self._components.get(name)

    @property
    def message_bus(self) -> MessageBus:
        """Get the message bus."""
        return self._message_bus

    @property
    def is_paper(self) -> bool:
        """Check if running in paper mode."""
        return self.mode == TradingMode.PAPER

    @property
    def is_live(self) -> bool:
        """Check if running in live mode."""
        return self.mode == TradingMode.LIVE

    @property
    def is_running(self) -> bool:
        """Check if kernel is running."""
        return self.state == KernelState.RUNNING

    @property
    def uptime_seconds(self) -> float:
        """Get kernel uptime in seconds."""
        if self._start_time_ns is None:
            return 0.0
        return (time.time_ns() - self._start_time_ns) / 1e9

    def start(self) -> None:
        """
        Start the trading kernel.

        Initializes all components and begins event processing.
        """
        if self.state == KernelState.RUNNING:
            logger.warning("Kernel already running")
            return

        self._start_time_ns = time.time_ns()
        self.state = KernelState.RUNNING

        # Subscribe to system events
        self._message_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal)
        self._message_bus.subscribe(EventType.ORDER_FILLED, self._on_trade)
        self._message_bus.subscribe(EventType.ERROR, self._on_error)

        logger.info(f"Kernel started in {self.mode.name} mode")
        if self.is_paper:
            logger.info("PAPER MODE - No real orders will be executed")
        else:
            logger.warning("LIVE MODE - Real money trading enabled!")

    def stop(self) -> None:
        """Stop the trading kernel."""
        if self.state != KernelState.RUNNING:
            logger.warning("Kernel not running")
            return

        self.state = KernelState.STOPPED
        logger.info(f"Kernel stopped after {self.uptime_seconds:.1f}s uptime")
        logger.info(f"Stats: {self._signal_count} signals, {self._trade_count} trades")

    def dispose(self) -> None:
        """Dispose the kernel and release resources."""
        if self.state == KernelState.RUNNING:
            self.stop()
        self.state = KernelState.DISPOSED
        self._components.clear()
        logger.info("Kernel disposed")

    def _on_signal(self, event: Event) -> None:
        """Handle signal events."""
        self._signal_count += 1

    def _on_trade(self, event: Event) -> None:
        """Handle trade events."""
        self._trade_count += 1

    def _on_error(self, event: Event) -> None:
        """Handle error events."""
        logger.error(f"Error event: {event}")
        if self.state == KernelState.RUNNING:
            self.state = KernelState.DEGRADED

    def stats(self) -> Dict[str, Any]:
        """Get kernel statistics."""
        return {
            "mode": self.mode.name,
            "state": self.state.name,
            "uptime_seconds": self.uptime_seconds,
            "signal_count": self._signal_count,
            "trade_count": self._trade_count,
            "components": list(self._components.keys()),
            "message_bus_stats": self._message_bus.stats(),
        }


# Convenience function for creating kernels
def create_kernel(mode: str = "paper", **kwargs) -> TradingKernel:
    """
    Create a trading kernel.

    Args:
        mode: "paper" or "live"
        **kwargs: Additional config options

    Returns:
        Configured TradingKernel
    """
    trading_mode = TradingMode.PAPER if mode.lower() == "paper" else TradingMode.LIVE
    return TradingKernel(mode=trading_mode, **kwargs)
