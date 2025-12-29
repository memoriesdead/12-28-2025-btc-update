# Sovereign Trader

## Gold-Standard Algorithmic Trading System

**Philosophy:** `impact > 2×fees = TRADE`

No predictions. No guessing. Pure deterministic math. Let the data speak.

---

## Architecture

Based on institutional-grade patterns from:

| Source | Stars | What We Use |
|--------|-------|-------------|
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | 5K+ | Rust+Python hybrid, 52ns latency, event-driven |
| [LMAX Disruptor](https://lmax-exchange.github.io/disruptor/) | 17K+ | Lock-free ring buffer, 6M orders/sec |
| [Freqtrade](https://github.com/freqtrade/freqtrade) | 45K | Exchange adapter pattern |
| [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | 10K+ | Paper/Live mode switching |
| [CCXT](https://github.com/ccxt/ccxt) | 35K+ | 100+ exchange unified API |

### Performance Benchmarks

| Component | Latency | Source |
|-----------|---------|--------|
| LMAX Disruptor | 52ns | [Performance Results](https://github.com/LMAX-Exchange/disruptor/wiki/Performance-Results) |
| Our C++ Parsers | 700-800ns | Measured (dex_benchmark_standalone.cpp) |
| Industry Average | 32,000ns+ | ArrayBlockingQueue comparison |

---

## The Deterministic Approach

### 4-Layer Pipeline

```
Layer 1: BLOCKCHAIN DETECTION (C++ - 8 microseconds)
   │  "50 BTC just hit Coinbase deposit address"
   │  Source: Bitcoin mempool monitoring
   ▼
Layer 2: HISTORICAL FLOW ANALYSIS
   │  "Last 10 deposits of this size → 1.5% price drop"
   │  Source: correlation.db, flow_data.db
   ▼
Layer 3: ORDER BOOK IMPACT CALCULATION
   │  "Current depth shows 0.15% slippage for this size"
   │  Source: Real-time orderbook from 23 exchanges
   ▼
Layer 4: EXECUTION DECISION
   │  "0.15% impact > 0.07% fees (2×) = EXECUTE"
   │  Action: Place order via CCXT
   ▼
   TRADE or SKIP (pure math, no emotion)
```

### The Math

```
IF expected_impact > (total_fees × min_multiple):
    EXECUTE TRADE
ELSE:
    SKIP

Where:
- expected_impact = historical_correlation × current_orderbook_depth
- total_fees = maker_fee + taker_fee + slippage
- min_multiple = 2.0 (configurable)
```

### Why This Works

1. **Not Prediction** - We don't predict price movement
2. **Deterministic** - Same input = same output, always
3. **Edge** - Mempool detection gives us ~10 second advantage
4. **Math** - Only trade when math guarantees profit after fees

---

## Directory Structure

```
sovereign/
├── run.py                        # Entry point
│                                 # python run.py --mode paper
│                                 # python run.py --mode live
│
├── cpp_runner/                   # C++ Blockchain Detection Layer
│   ├── include/
│   │   ├── flow_detector.hpp     # Mempool monitoring
│   │   ├── tx_decoder.hpp        # Transaction parsing
│   │   ├── address_database.hpp  # Exchange address lookup
│   │   └── order_book_types.hpp  # Shared types
│   └── src/
│       ├── main.cpp              # Blockchain runner
│       └── flow_detector.cpp     # Detection logic
│
├── crates/cpp_handlers/          # C++ DEX Parsers (700ns latency)
│   ├── hyperliquid.hpp           # Hyperliquid parser
│   ├── dydx.hpp                  # dYdX v4 parser
│   ├── injective.hpp             # Injective parser
│   ├── unified_dex_feed.hpp      # Cross-DEX arbitrage
│   └── dex_benchmark_standalone.cpp  # Latency benchmark
│
├── sovereign_trader/             # Python Strategy Layer
│   ├── core/
│   │   ├── config.py             # 23 verified exchanges
│   │   ├── message_bus.py        # LMAX Disruptor pattern
│   │   └── kernel.py             # NautilusKernel pattern
│   │
│   ├── adapters/
│   │   ├── cex/                  # Coinbase, OKX, Kraken...
│   │   └── dex/                  # Hyperliquid, dYdX, Injective
│   │
│   ├── data/
│   │   ├── ccxt_feed.py          # Exchange data via CCXT
│   │   ├── depth_calculator.py   # Order book impact math
│   │   └── flow_history.py       # Historical correlation
│   │
│   ├── execution/
│   │   └── executor.py           # Order execution
│   │
│   ├── signals/
│   │   └── generator.py          # Signal generation
│   │
│   ├── blockchain/               # Our unique edge
│   │   └── detector.py           # Mempool detection bridge
│   │
│   └── model/
│       ├── types.py              # OrderBook, Trade, Position
│       └── events.py             # Event-driven types
│
└── venv/                         # Python virtual environment
```

---

## Verified Exchanges (23)

### US Exchanges (Direct)
- Coinbase, Gemini, Kraken, Bitstamp

### International (via Frankfurt Proxy)
- OKX, HTX, KuCoin, Gate, MEXC, Bitget, Phemex, Deribit
- Poloniex, Bitfinex, CoinEx, BingX, BitMart, LBank
- WhiteBit, Crypto.com, XT, Probit, AscendEX

### DEX (Local Nodes)
- Hyperliquid (localhost:3001)
- dYdX v4 (localhost:26657)
- Injective (localhost:9090)

---

## Key Databases

| Database | Size | Purpose |
|----------|------|---------|
| `walletexplorer_addresses.db` | 1.5GB | Exchange deposit addresses |
| `address_clusters.db` | 1.3GB | Wallet clustering data |
| `addresses.bin` | 137MB | Binary address lookup |
| `trades.db` | Active | Trade history |
| `correlation.db` | Active | Flow correlation data |

---

## Configuration

### Trading Parameters (config.py)

```python
initial_capital = 100.0
max_positions = 4
position_size_pct = 0.25
max_leverage = 125
default_leverage = 20
stop_loss_pct = 0.01
take_profit_pct = 0.02
min_flow_btc = 5.0          # Minimum deposit to trigger
min_impact_multiple = 2.0    # impact > 2×fees
```

### Fee Structure

| Exchange Type | Maker | Taker |
|---------------|-------|-------|
| CEX Average | 0.02% | 0.05% |
| Hyperliquid | 0.02% | 0.035% |
| dYdX | 0.02% | 0.05% |
| Injective | 0.05% | 0.10% |

---

## Running

### Paper Trading (Safe)
```bash
cd sovereign
python run.py --mode paper
```

### Live Trading (Real Money)
```bash
cd sovereign
python run.py --mode live
```

### C++ Benchmark
```bash
cd crates/cpp_handlers
g++ -std=c++17 -O3 -o benchmark dex_benchmark_standalone.cpp
./benchmark
```

---

## Research Sources

### Architecture
- [NautilusTrader Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)
- [LMAX Architecture - Martin Fowler](https://martinfowler.com/articles/lmax.html)
- [NautilusTrader DeepWiki](https://deepwiki.com/nautechsystems/nautilus_trader/1-overview)

### Performance
- [LMAX Disruptor Performance](https://github.com/LMAX-Exchange/disruptor/wiki/Performance-Results)
- 52ns vs 32,757ns (ArrayBlockingQueue) = 600x faster

### Trading Systems
- [Freqtrade](https://github.com/freqtrade/freqtrade) - Exchange adapters
- [QuantConnect Lean](https://github.com/QuantConnect/Lean) - Paper/Live mode
- [pysystemtrade](https://github.com/robcarver17/pysystemtrade) - "Let data speak"
- [QLib](https://github.com/microsoft/qlib) - Data pipeline patterns

---

## VPS Access

```bash
ssh root@31.97.211.217
cd /root/sovereign
python run.py --mode paper
```

---

## Philosophy

> "We don't predict the future. We calculate what WILL happen based on order book depth and historical correlation. The math either works or it doesn't. No emotion. No guessing. Let the data speak."

**impact > 2×fees = TRADE**

---

## Backup

Full codebase backed up at:
https://github.com/memoriesdead/12-28-2025-btc-update

---

*Last updated: 2025-12-28*
