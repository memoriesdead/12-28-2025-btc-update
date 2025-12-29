# DEX Node Cross-Reference

## Overview

| DEX | In CCXT | Has Own Node | Node Binary | Status |
|-----|---------|--------------|-------------|--------|
| Hyperliquid | ✅ | ✅ | hl-visor | ✅ RUNNING |
| dYdX v4 | ✅ | ✅ | dydxprotocold | ❌ NEED TO INSTALL |
| Injective | ❌ | ✅ | injectived | ❌ NEED TO INSTALL |
| Sei | ❌ | ✅ | seid | ❌ NEED TO INSTALL |
| Paradex | ✅ | ⚠️ | Starknet node | ❌ NEED STARKNET |
| Apex | ✅ | ❌ | Uses other chains | N/A |
| Vertex | ❌ | ❌ | On Arbitrum | N/A |
| GMX | ❌ | ❌ | On Arbitrum | N/A |

## Priority: DEXes with Own Nodes + CCXT Support

### 1. Hyperliquid ✅ DONE
- **Node**: hl-visor
- **Location**: /root/hyperliquid/
- **API**: localhost:3001/info
- **Fee**: 0.035%
- **Data**: trades, orderbook, funding, liquidations

### 2. dYdX v4 (PRIORITY)
- **Binary**: dydxprotocold
- **Download**: https://github.com/dydxprotocol/v4-chain/releases
- **Docs**: https://docs.dydx.exchange/infrastructure_providers-validators/set_up_full_node
- **Fee**: 0.02% maker, 0.05% taker
- **Data**: orderbook, trades, funding, positions

### 3. Injective (PRIORITY)
- **Binary**: injectived
- **Download**: https://github.com/InjectiveLabs/injective-chain-releases
- **Docs**: https://docs.injective.network/nodes/validators/mainnet
- **Fee**: 0.10%
- **Data**: orderbook, trades, oracle prices

### 4. Sei
- **Binary**: seid
- **Build from**: https://github.com/sei-protocol/sei-chain
- **Docs**: https://docs.sei.io/node/node-operators
- **Fee**: 0.10%
- **Data**: orderbook, trades

## DEXes NOT in CCXT (Add to CCXT or use SDK)

| DEX | Has Node | SDK Available |
|-----|----------|---------------|
| Injective | ✅ | ✅ Python SDK |
| Sei | ✅ | ✅ TypeScript SDK |
| Vertex | ❌ (Arbitrum) | ✅ Python SDK |
| GMX | ❌ (Arbitrum) | ⚠️ Contract calls |
| Drift | ❌ (Solana) | ✅ TypeScript SDK |
| Jupiter | ❌ (Solana) | ✅ TypeScript SDK |

## Data Advantage Strategy

Each node gives us:
1. **Zero latency** - No API rate limits
2. **Full orderbook** - All depth, not just top 20
3. **All trades** - Every fill, not sampled
4. **Funding history** - Complete historical data
5. **Liquidation data** - See forced closes

## Installation Scripts

### dYdX v4 Node
```bash
# Download binary
wget https://github.com/dydxprotocol/v4-chain/releases/download/protocol/v5.0.5/dydxprotocold-v5.0.5-linux-amd64.tar.gz
tar -xzf dydxprotocold-v5.0.5-linux-amd64.tar.gz
mv dydxprotocold /root/dydx/

# Initialize
./dydxprotocold init mynode --chain-id dydx-mainnet-1 --home /root/.dydx

# Start non-validator
./dydxprotocold start --non-validating-full-node=true --home /root/.dydx
```

### Injective Node
```bash
# Download
wget https://github.com/InjectiveLabs/injective-chain-releases/releases/download/v1.12.1-1705909076/linux-amd64.zip
unzip linux-amd64.zip
mv injectived /root/injective/

# Initialize
./injectived init mynode --chain-id injective-1 --home /root/.injectived

# Start
./injectived start --home /root/.injectived
```

### Sei Node
```bash
# Build from source
git clone https://github.com/sei-protocol/sei-chain
cd sei-chain
git checkout v3.0.0
make install

# Initialize
seid init mynode --chain-id sei-mainnet-1 --home /root/.sei

# Start
seid start --home /root/.sei
```

## Fee Comparison

| DEX | Taker Fee | Required Impact (2x) |
|-----|-----------|---------------------|
| Hyperliquid | 0.035% | 0.07% |
| dYdX | 0.050% | 0.10% |
| Vertex | 0.020% | 0.04% |
| Injective | 0.100% | 0.20% |
| Sei | 0.100% | 0.20% |

## Action Items

1. [x] Hyperliquid node running
2. [ ] Install dYdX v4 node
3. [ ] Install Injective node
4. [ ] Add Injective to CCXT (or use SDK)
5. [ ] Cross-reference data across all nodes
6. [ ] Build unified data feed
