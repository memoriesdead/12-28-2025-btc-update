"""Core module - Config, MessageBus, and Kernel."""
from .config import TradingConfig, get_config
from .message_bus import MessageBus, get_message_bus
from .kernel import TradingKernel, TradingMode, create_kernel
