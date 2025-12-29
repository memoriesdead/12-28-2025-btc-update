/**
 * Order Book Types - Core Data Structures
 *
 * PURE DATA. NO MOCK. MATH NEVER LIES.
 * ALL 110 CCXT EXCHANGES - COMPLETE COVERAGE
 *
 * This file defines the fundamental data structures for the high-performance
 * order book caching system. Designed for sub-microsecond operations.
 */

#pragma once

#include <vector>
#include <array>
#include <chrono>
#include <atomic>
#include <string>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <unordered_map>

namespace sovereign {

// ============================================================================
// EXCHANGE DEFINITIONS - ALL 110 CCXT EXCHANGES
// ============================================================================

enum class Exchange : uint8_t {
    // === PERPETUAL EXCHANGES (44) - Have leverage, mark price, funding ===
    APEX = 0,
    ARKHAM,
    ASCENDEX,
    BACKPACK,
    BIGONE,
    BINANCE,
    BINANCECOINM,
    BINANCEUSDM,
    BINGX,
    BITFINEX,
    BITFLYER,
    BITGET,
    BITMART,
    BITMEX,
    BITRUE,
    BLOFIN,
    BULLISH,
    BYBIT,
    COINBASE,
    COINBASEADVANCED,
    COINBASEINTERNATIONAL,
    COINCATCH,
    COINEX,
    CRYPTOCOM,
    DEEPCOIN,
    DEFX,
    DELTA,
    DERIBIT,
    DERIVE,
    DIGIFINEX,
    DYDX,
    FMFWIO,
    GATE,
    GATEIO,
    GEMINI,
    HASHKEY,
    HIBACHI,
    HITBTC,
    HTX,
    HUOBI,
    HYPERLIQUID,
    KRAKENFUTURES,
    KUCOINFUTURES,
    LBANK,
    MEXC,
    MODETRADE,
    MYOKX,
    OKX,
    OKXUS,
    ONETRADING,
    PARADEX,
    PHEMEX,
    POLONIEX,
    TOOBIT,
    WHITEBIT,
    WOOFIPRO,
    XT,
    ZEBPAY,

    // === SPOT-ONLY EXCHANGES (51) - No perpetuals ===
    ALPACA,
    BEQUANT,
    BINANCEUS,
    BIT2C,
    BITBANK,
    BITBNS,
    BITHUMB,
    BITOPRO,
    BITSO,
    BITSTAMP,
    BITTEAM,
    BITTRADE,
    BITVAVO,
    BLOCKCHAINCOM,
    BTCALPHA,
    BTCBOX,
    BTCMARKETS,
    BTCTURK,
    CEX,
    COINBASEEXCHANGE,
    COINCHECK,
    COINMATE,
    COINMETRO,
    COINONE,
    COINSPH,
    COINSPOT,
    CRYPTOMUS,
    EXMO,
    FOXBIT,
    HOLLAEX,
    INDEPENDENTRESERVE,
    INDODAX,
    KRAKEN,
    KUCOIN,
    LATOKEN,
    LUNO,
    MERCADO,
    NDAX,
    NOVADAX,
    OCEANEX,
    OXFUN,
    P2B,
    PAYMIUM,
    PROBIT,
    TIMEX,
    TOKOCRYPTO,
    UPBIT,
    WAVESEXCHANGE,
    WOO,
    YOBIT,
    ZAIF,
    ZONDA,

    COUNT  // Sentinel for array sizing (110 total)
};

// Exchange name lookup (compile-time) - ALL 110
constexpr const char* EXCHANGE_NAMES[] = {
    // Perpetual exchanges (44)
    "apex", "arkham", "ascendex", "backpack", "bigone",
    "binance", "binancecoinm", "binanceusdm", "bingx", "bitfinex",
    "bitflyer", "bitget", "bitmart", "bitmex", "bitrue",
    "blofin", "bullish", "bybit", "coinbase", "coinbaseadvanced",
    "coinbaseinternational", "coincatch", "coinex", "cryptocom", "deepcoin",
    "defx", "delta", "deribit", "derive", "digifinex",
    "dydx", "fmfwio", "gate", "gateio", "gemini",
    "hashkey", "hibachi", "hitbtc", "htx", "huobi",
    "hyperliquid", "krakenfutures", "kucoinfutures", "lbank", "mexc",
    "modetrade", "myokx", "okx", "okxus", "onetrading",
    "paradex", "phemex", "poloniex", "toobit", "whitebit",
    "woofipro", "xt", "zebpay",
    // Spot-only exchanges (51)
    "alpaca", "bequant", "binanceus", "bit2c", "bitbank",
    "bitbns", "bithumb", "bitopro", "bitso", "bitstamp",
    "bitteam", "bittrade", "bitvavo", "blockchaincom", "btcalpha",
    "btcbox", "btcmarkets", "btcturk", "cex", "coinbaseexchange",
    "coincheck", "coinmate", "coinmetro", "coinone", "coinsph",
    "coinspot", "cryptomus", "exmo", "foxbit", "hollaex",
    "independentreserve", "indodax", "kraken", "kucoin", "latoken",
    "luno", "mercado", "ndax", "novadax", "oceanex",
    "oxfun", "p2b", "paymium", "probit", "timex",
    "tokocrypto", "upbit", "wavesexchange", "woo", "yobit",
    "zaif", "zonda"
};

inline const char* exchange_name(Exchange ex) {
    if (static_cast<size_t>(ex) >= static_cast<size_t>(Exchange::COUNT)) {
        return "unknown";
    }
    return EXCHANGE_NAMES[static_cast<size_t>(ex)];
}

inline Exchange exchange_from_name(const std::string& name) {
    for (size_t i = 0; i < static_cast<size_t>(Exchange::COUNT); ++i) {
        if (name == EXCHANGE_NAMES[i]) {
            return static_cast<Exchange>(i);
        }
    }
    return Exchange::COUNT;  // Invalid
}

// Check if exchange has perpetuals (first 58 in enum)
inline bool has_perpetuals(Exchange ex) {
    return static_cast<size_t>(ex) <= static_cast<size_t>(Exchange::ZEBPAY);
}

// ============================================================================
// INSTRUMENT TYPES - ALL 7 TRADING INSTRUMENTS
// ============================================================================

enum class InstrumentType : uint8_t {
    SPOT = 0,           // 1x, own the asset
    MARGIN = 1,         // 3-10x, collateral-based
    PERPETUAL = 2,      // up to 500x, funding every 8hrs
    FUTURES = 3,        // up to 125x, expiration dates
    OPTIONS = 4,        // premium-based, Greeks
    INVERSE = 5,        // BTC-denominated contracts
    LEVERAGED_TOKEN = 6,// fixed 3x, daily rebalance
    INST_COUNT = 7
};

constexpr const char* INSTRUMENT_NAMES[] = {
    "spot", "margin", "perpetual", "futures", "options", "inverse", "leveraged_token"
};

inline const char* instrument_name(InstrumentType t) {
    if (static_cast<size_t>(t) >= static_cast<size_t>(InstrumentType::INST_COUNT)) {
        return "unknown";
    }
    return INSTRUMENT_NAMES[static_cast<size_t>(t)];
}

inline InstrumentType instrument_from_name(const std::string& name) {
    for (size_t i = 0; i < static_cast<size_t>(InstrumentType::INST_COUNT); ++i) {
        if (name == INSTRUMENT_NAMES[i]) {
            return static_cast<InstrumentType>(i);
        }
    }
    return InstrumentType::INST_COUNT;  // Invalid
}

// Bitfield helpers for supported instruments per exchange
constexpr uint8_t INST_SPOT = 1 << 0;
constexpr uint8_t INST_MARGIN = 1 << 1;
constexpr uint8_t INST_PERPETUAL = 1 << 2;
constexpr uint8_t INST_FUTURES = 1 << 3;
constexpr uint8_t INST_OPTIONS = 1 << 4;
constexpr uint8_t INST_INVERSE = 1 << 5;
constexpr uint8_t INST_LEVERAGED_TOKEN = 1 << 6;

// Check if exchange supports an instrument type
inline bool supports_instrument(uint8_t supported, InstrumentType type) {
    return (supported & (1 << static_cast<uint8_t>(type))) != 0;
}

// ============================================================================
// EXCHANGE CONFIGURATION - ALL EXCHANGES
// ============================================================================

struct ExchangeConfig {
    Exchange id;
    const char* ws_url;
    const char* rest_url;
    const char* symbol;
    const char* spot_symbol;      // For spot trading
    bool has_websocket;
    bool has_perpetual;
    int max_leverage;
    double fee_pct;
};

// Static configuration for ALL exchanges - PURE DATA from CCXT/docs
// Using inline function to avoid large static array
inline ExchangeConfig get_exchange_config(Exchange ex) {
    switch (ex) {
        // ============ PERPETUAL EXCHANGES ============
        case Exchange::APEX:
            return {ex, "wss://ws.apex.exchange/ws", "https://api.apex.exchange/api/v1/depth",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::ARKHAM:
            return {ex, "", "https://api.arkhamintelligence.com/orderbook",
                    "BTC/USDT:USDT", "BTC/USDT", false, true, 50, 0.003};
        case Exchange::ASCENDEX:
            return {ex, "wss://ascendex.com/1/api/pro/v1/stream", "https://ascendex.com/api/pro/v2/futures/order-book",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::BACKPACK:
            return {ex, "wss://ws.backpack.exchange", "https://api.backpack.exchange/api/v1/depth",
                    "BTC/USDC:USDC", "BTC/USDC", true, true, 50, 0.002};
        case Exchange::BIGONE:
            return {ex, "wss://big.one/ws/v2", "https://big.one/api/v3/asset_pairs/BTC-USD/depth",
                    "BTC/USD:BTC", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::BINANCE:
            return {ex, "wss://fstream.binance.com/ws", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 125, 0.001};
        case Exchange::BINANCECOINM:
            return {ex, "wss://dstream.binance.com/ws", "https://dapi.binance.com/dapi/v1/depth?symbol=BTCUSD_PERP&limit=50",
                    "BTC/USD:BTC", "BTC/USD", true, true, 125, 0.001};
        case Exchange::BINANCEUSDM:
            return {ex, "wss://fstream.binance.com/ws", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 125, 0.001};
        case Exchange::BINGX:
            return {ex, "wss://open-api-swap.bingx.com/swap-market", "https://open-api.bingx.com/openApi/swap/v2/quote/depth",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 150, 0.002};
        case Exchange::BITFINEX:
            return {ex, "wss://api-pub.bitfinex.com/ws/2", "https://api-pub.bitfinex.com/v2/book/tBTCF0:USTF0/P0",
                    "BTC/USDT:USDT", "BTC/USD", true, true, 100, 0.002};
        case Exchange::BITFLYER:
            return {ex, "wss://ws.lightstream.bitflyer.com/json-rpc", "https://api.bitflyer.com/v1/board?product_code=FX_BTC_JPY",
                    "BTC/JPY:JPY", "BTC/JPY", true, true, 4, 0.002};
        case Exchange::BITGET:
            return {ex, "wss://ws.bitget.com/mix/v1/stream", "https://api.bitget.com/api/mix/v1/market/depth?symbol=BTCUSDT_UMCBL&limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 125, 0.002};
        case Exchange::BITMART:
            return {ex, "wss://ws-manager-compress.bitmart.com/api?protocol=1.1", "https://api-cloud.bitmart.com/contract/public/depth?symbol=BTCUSDT",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::BITMEX:
            return {ex, "wss://ws.bitmex.com/realtime", "https://www.bitmex.com/api/v1/orderBook/L2?symbol=XBTUSD&depth=50",
                    "BTC/USD:BTC", "XBTUSD", true, true, 100, 0.001};
        case Exchange::BITRUE:
            return {ex, "wss://futures.bitrue.com/kline-api/ws", "https://futures.bitrue.com/fapi/v1/depth?symbol=BTCUSDT&limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 125, 0.002};
        case Exchange::BLOFIN:
            return {ex, "wss://openapi.blofin.com/ws/public", "https://openapi.blofin.com/api/v1/market/books?instId=BTC-USDT",
                    "BTC/USDC:USDC", "BTC/USDT", true, true, 150, 0.002};
        case Exchange::BULLISH:
            return {ex, "wss://api.bullish.com/ws", "https://api.bullish.com/trading/orderbooks",
                    "BTC/USDC:USDC", "BTC/USDC", true, true, 20, 0.002};
        case Exchange::BYBIT:
            return {ex, "wss://stream.bybit.com/v5/public/linear", "https://api.bybit.com/v5/market/orderbook?category=linear&symbol=BTCUSDT&limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.001};
        case Exchange::COINBASE:
            return {ex, "wss://ws-feed.exchange.coinbase.com", "https://api.exchange.coinbase.com/products/BTC-USD/book?level=2",
                    "BTC/USD:USD", "BTC/USD", true, true, 10, 0.005};
        case Exchange::COINBASEADVANCED:
            return {ex, "wss://ws-feed.exchange.coinbase.com", "https://api.coinbase.com/api/v3/brokerage/product_book",
                    "BTC/USD:USD", "BTC/USD", true, true, 10, 0.005};
        case Exchange::COINBASEINTERNATIONAL:
            return {ex, "wss://ws-md.international.coinbase.com", "https://api.international.coinbase.com/api/v1/orderbook",
                    "BTC/USDC:USDC", "BTC/USDC", true, true, 10, 0.002};
        case Exchange::COINCATCH:
            return {ex, "wss://ws.coincatch.com/public", "https://api.coincatch.com/api/mix/v1/market/depth",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 125, 0.002};
        case Exchange::COINEX:
            return {ex, "wss://socket.coinex.com/v2/futures", "https://api.coinex.com/perpetual/v1/market/depth?market=BTCUSDT&merge=0&limit=50",
                    "BTC/USDC:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::CRYPTOCOM:
            return {ex, "wss://stream.crypto.com/v2/market", "https://api.crypto.com/v2/public/get-book",
                    "BTC/USD:USD", "BTC/USD", true, true, 50, 0.002};
        case Exchange::DEEPCOIN:
            return {ex, "wss://ws.deepcoin.com/ws", "https://api.deepcoin.com/deepcoin/market/orderbook",
                    "BTC/USD:BTC", "BTC/USDT", true, true, 125, 0.002};
        case Exchange::DEFX:
            return {ex, "", "https://api.defx.com/orderbook",
                    "BTC/USDC:USDC", "BTC/USDC", false, true, 50, 0.002};
        case Exchange::DELTA:
            return {ex, "wss://socket.delta.exchange", "https://api.delta.exchange/v2/l2orderbook/BTCUSDT",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::DERIBIT:
            return {ex, "wss://www.deribit.com/ws/api/v2", "https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-PERPETUAL&depth=50",
                    "BTC/USD:BTC", "BTC-PERPETUAL", true, true, 50, 0.001};
        case Exchange::DERIVE:
            return {ex, "", "https://api.derive.xyz/orderbook",
                    "BTC/USD:USD", "BTC/USD", false, true, 20, 0.002};
        case Exchange::DIGIFINEX:
            return {ex, "wss://openapi.digifinex.com/ws/v1/", "https://openapi.digifinex.com/v3/order_book?symbol=btc_usdt&limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::DYDX:
            return {ex, "wss://api.dydx.exchange/v3/ws", "https://api.dydx.exchange/v3/orderbook/BTC-USD",
                    "BTC/USD:USD", "BTC/USD", true, true, 20, 0.001};
        case Exchange::FMFWIO:
            return {ex, "wss://api.fmfw.io/ws", "https://api.fmfw.io/api/3/public/orderbook/BTCUSDT",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::GATE:
            return {ex, "wss://fx-ws.gateio.ws/v4/ws/usdt", "https://api.gateio.ws/api/v4/futures/usdt/order_book?contract=BTC_USDT&limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::GATEIO:
            return {ex, "wss://fx-ws.gateio.ws/v4/ws/usdt", "https://api.gateio.ws/api/v4/futures/usdt/order_book?contract=BTC_USDT&limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::GEMINI:
            return {ex, "wss://api.gemini.com/v1/marketdata/btcusd", "https://api.gemini.com/v1/book/btcusd",
                    "BTC/GUSD:GUSD", "BTC/USD", true, true, 100, 0.004};
        case Exchange::HASHKEY:
            return {ex, "wss://stream-pro.hashkey.com/quote/ws/v1", "https://api-pro.hashkey.com/quote/v1/depth",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 50, 0.002};
        case Exchange::HIBACHI:
            return {ex, "wss://ws.hibachi.xyz", "https://api.hibachi.xyz/orderbook",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 50, 0.002};
        case Exchange::HITBTC:
            return {ex, "wss://api.hitbtc.com/api/3/ws/public", "https://api.hitbtc.com/api/3/public/orderbook/BTCUSDT",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 75, 0.002};
        case Exchange::HTX:
            return {ex, "wss://api.hbdm.com/linear-swap-ws", "https://api.hbdm.com/linear-swap-ex/market/depth?contract_code=BTC-USDT&type=step0",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 200, 0.002};
        case Exchange::HUOBI:
            return {ex, "wss://api.hbdm.com/linear-swap-ws", "https://api.hbdm.com/linear-swap-ex/market/depth?contract_code=BTC-USDT&type=step0",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 200, 0.002};
        case Exchange::HYPERLIQUID:
            return {ex, "wss://api.hyperliquid.xyz/ws", "https://api.hyperliquid.xyz/info",
                    "BTC/USDC:USDC", "BTC/USDC", true, true, 50, 0.001};
        case Exchange::KRAKENFUTURES:
            return {ex, "wss://futures.kraken.com/ws/v1", "https://futures.kraken.com/derivatives/api/v3/orderbook?symbol=PI_XBTUSD",
                    "BTC/USD:BTC", "PI_XBTUSD", true, true, 50, 0.002};
        case Exchange::KUCOINFUTURES:
            return {ex, "wss://ws-api-futures.kucoin.com", "https://api-futures.kucoin.com/api/v1/level2/snapshot?symbol=XBTUSDTM",
                    "BTC/USDT:USDT", "XBTUSDTM", true, true, 100, 0.002};
        case Exchange::LBANK:
            return {ex, "wss://www.lbkex.net/ws/V2/", "https://api.lbank.info/v2/depth.do?symbol=btc_usdt&size=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 125, 0.002};
        case Exchange::MEXC:
            return {ex, "wss://contract.mexc.com/ws", "https://contract.mexc.com/api/v1/contract/depth/BTC_USDT",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 200, 0.002};
        case Exchange::MODETRADE:
            return {ex, "", "https://api.modetrade.com/orderbook",
                    "BTC/USDT:USDT", "BTC/USDT", false, true, 50, 0.002};
        case Exchange::MYOKX:
            return {ex, "wss://ws.okx.com:8443/ws/v5/public", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT-SWAP&sz=50",
                    "BTC/USD:BTC", "BTC/USDT", true, true, 125, 0.001};
        case Exchange::OKX:
            return {ex, "wss://ws.okx.com:8443/ws/v5/public", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT-SWAP&sz=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 125, 0.001};
        case Exchange::OKXUS:
            return {ex, "wss://ws.okx.com:8443/ws/v5/public", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT-SWAP&sz=50",
                    "BTC/USD:BTC", "BTC/USDT", true, true, 125, 0.001};
        case Exchange::ONETRADING:
            return {ex, "wss://ws.onetrading.com", "https://api.onetrading.com/public/v1/order-book/BTC_EUR",
                    "BTC/EUR:EUR", "BTC/EUR", true, true, 5, 0.002};
        case Exchange::PARADEX:
            return {ex, "wss://ws.api.paradex.trade/v1", "https://api.paradex.trade/v1/orderbook",
                    "BTC/USD:USDC", "BTC/USD", true, true, 20, 0.002};
        case Exchange::PHEMEX:
            return {ex, "wss://phemex.com/ws", "https://api.phemex.com/md/orderbook?symbol=BTCUSD",
                    "BTC/USD:BTC", "BTCUSD", true, true, 100, 0.002};
        case Exchange::POLONIEX:
            return {ex, "wss://ws.poloniex.com/ws/public", "https://api.poloniex.com/markets/BTC_USDT/orderBook?limit=50",
                    "BTC/USDT:USDT", "BTC_USDT", true, true, 75, 0.003};
        case Exchange::TOOBIT:
            return {ex, "wss://ws.toobit.com/ws", "https://api.toobit.com/quote/v1/depth",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 150, 0.002};
        case Exchange::WHITEBIT:
            return {ex, "wss://api.whitebit.com/ws", "https://whitebit.com/api/v4/public/orderbook/BTC_USDT?limit=50",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 100, 0.002};
        case Exchange::WOOFIPRO:
            return {ex, "wss://ws.woo.org/ws/stream", "https://api.woo.org/v1/orderbook/PERP_BTC_USDT",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 20, 0.002};
        case Exchange::XT:
            return {ex, "wss://stream.xt.com/public", "https://api.xt.com/future/market/v1/public/q/depth",
                    "BTC/USDT:USDT", "BTC/USDT", true, true, 125, 0.002};
        case Exchange::ZEBPAY:
            return {ex, "", "https://www.zebapi.com/pro/v1/market/BTC-USDT/orderbook",
                    "BTC/USDT:USDT", "BTC/USDT", false, true, 75, 0.005};

        // ============ SPOT-ONLY EXCHANGES ============
        case Exchange::ALPACA:
            return {ex, "wss://stream.data.alpaca.markets/v2/crypto", "https://data.alpaca.markets/v1beta3/crypto/us/orderbooks",
                    "", "BTC/USD", true, false, 1, 0.002};
        case Exchange::BEQUANT:
            return {ex, "wss://api.bequant.io/api/3/ws/public", "https://api.bequant.io/api/3/public/orderbook",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::BINANCEUS:
            return {ex, "wss://stream.binance.us:9443/ws", "https://api.binance.us/api/v3/depth?symbol=BTCUSD&limit=50",
                    "", "BTC/USD", true, false, 1, 0.001};
        case Exchange::BIT2C:
            return {ex, "", "https://bit2c.co.il/Exchanges/BtcNis/orderbook.json",
                    "", "BTC/NIS", false, false, 1, 0.005};
        case Exchange::BITBANK:
            return {ex, "wss://stream.bitbank.cc/socket.io", "https://public.bitbank.cc/btc_jpy/depth",
                    "", "BTC/JPY", true, false, 1, 0.002};
        case Exchange::BITBNS:
            return {ex, "", "https://bitbns.com/order/fetchOrderbook",
                    "", "BTC/INR", false, false, 1, 0.005};
        case Exchange::BITHUMB:
            return {ex, "wss://pubwss.bithumb.com/pub/ws", "https://api.bithumb.com/public/orderbook/BTC_KRW",
                    "", "BTC/KRW", true, false, 1, 0.002};
        case Exchange::BITOPRO:
            return {ex, "wss://stream.bitopro.com:443/ws/v1/pub", "https://api.bitopro.com/v3/order-book/BTC_TWD",
                    "", "BTC/TWD", true, false, 1, 0.002};
        case Exchange::BITSO:
            return {ex, "wss://ws.bitso.com", "https://api.bitso.com/v3/order_book?book=btc_mxn",
                    "", "BTC/MXN", true, false, 1, 0.005};
        case Exchange::BITSTAMP:
            return {ex, "wss://ws.bitstamp.net", "https://www.bitstamp.net/api/v2/order_book/btcusd",
                    "", "BTC/USD", true, false, 1, 0.005};
        case Exchange::BITTEAM:
            return {ex, "", "https://bit.team/api/orderbook",
                    "", "BTC/USDT", false, false, 1, 0.002};
        case Exchange::BITTRADE:
            return {ex, "", "https://api-cloud.bittrade.co.jp/v1/orderbook",
                    "", "BTC/JPY", false, false, 1, 0.002};
        case Exchange::BITVAVO:
            return {ex, "wss://ws.bitvavo.com/v2", "https://api.bitvavo.com/v2/BTC-EUR/book",
                    "", "BTC/EUR", true, false, 1, 0.002};
        case Exchange::BLOCKCHAINCOM:
            return {ex, "wss://ws.blockchain.com/mercury-gateway/v1/ws", "https://api.blockchain.com/v3/exchange/l2/BTC-USD",
                    "", "BTC/USD", true, false, 1, 0.002};
        case Exchange::BTCALPHA:
            return {ex, "", "https://btc-alpha.com/api/v1/orderbook/BTC_USDT",
                    "", "BTC/USDT", false, false, 1, 0.002};
        case Exchange::BTCBOX:
            return {ex, "", "https://www.btcbox.co.jp/api/v1/depth",
                    "", "BTC/JPY", false, false, 1, 0.002};
        case Exchange::BTCMARKETS:
            return {ex, "wss://socket.btcmarkets.net/v2", "https://api.btcmarkets.net/v3/markets/BTC-AUD/orderbook",
                    "", "BTC/AUD", true, false, 1, 0.002};
        case Exchange::BTCTURK:
            return {ex, "wss://ws-feed-pro.btcturk.com", "https://api.btcturk.com/api/v2/orderbook?pairSymbol=BTCTRY",
                    "", "BTC/TRY", true, false, 1, 0.002};
        case Exchange::CEX:
            return {ex, "wss://ws.cex.io/ws", "https://cex.io/api/order_book/BTC/USD",
                    "", "BTC/USD", true, false, 1, 0.002};
        case Exchange::COINBASEEXCHANGE:
            return {ex, "wss://ws-feed.exchange.coinbase.com", "https://api.exchange.coinbase.com/products/BTC-USD/book?level=2",
                    "", "BTC/USD", true, false, 1, 0.005};
        case Exchange::COINCHECK:
            return {ex, "wss://ws-api.coincheck.com", "https://coincheck.com/api/order_books",
                    "", "BTC/JPY", true, false, 1, 0.002};
        case Exchange::COINMATE:
            return {ex, "wss://coinmate.io/api/websocket", "https://coinmate.io/api/orderBook?currencyPair=BTC_EUR",
                    "", "BTC/EUR", true, false, 1, 0.002};
        case Exchange::COINMETRO:
            return {ex, "wss://api.coinmetro.com/ws", "https://api.coinmetro.com/exchange/book/BTCEUR",
                    "", "BTC/EUR", true, false, 1, 0.002};
        case Exchange::COINONE:
            return {ex, "", "https://api.coinone.co.kr/orderbook?currency=btc",
                    "", "BTC/KRW", false, false, 1, 0.002};
        case Exchange::COINSPH:
            return {ex, "", "https://api.coins.ph/openapi/quote/v1/depth",
                    "", "BTC/PHP", false, false, 1, 0.002};
        case Exchange::COINSPOT:
            return {ex, "", "https://www.coinspot.com.au/pubapi/v2/orders/open/btc",
                    "", "BTC/AUD", false, false, 1, 0.005};
        case Exchange::CRYPTOMUS:
            return {ex, "", "https://api.cryptomus.com/v1/exchange/market/assets",
                    "", "BTC/USDT", false, false, 1, 0.002};
        case Exchange::EXMO:
            return {ex, "wss://ws-api.exmo.com:443/v1/public", "https://api.exmo.com/v1.1/order_book?pair=BTC_USDT",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::FOXBIT:
            return {ex, "", "https://api.foxbit.com.br/rest/v3/markets/btc-brl/orderbook",
                    "", "BTC/BRL", false, false, 1, 0.002};
        case Exchange::HOLLAEX:
            return {ex, "wss://api.hollaex.com/stream", "https://api.hollaex.com/v2/orderbook?symbol=btc-usdt",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::INDEPENDENTRESERVE:
            return {ex, "", "https://api.independentreserve.com/Public/GetOrderBook?primaryCurrencyCode=xbt&secondaryCurrencyCode=aud",
                    "", "BTC/AUD", false, false, 1, 0.005};
        case Exchange::INDODAX:
            return {ex, "wss://ws3.indodax.com/ws/", "https://indodax.com/api/btc_idr/depth",
                    "", "BTC/IDR", true, false, 1, 0.003};
        case Exchange::KRAKEN:
            return {ex, "wss://ws.kraken.com", "https://api.kraken.com/0/public/Depth?pair=XBTUSD&count=50",
                    "", "BTC/USD", true, false, 1, 0.002};
        case Exchange::KUCOIN:
            return {ex, "wss://ws-api-spot.kucoin.com", "https://api.kucoin.com/api/v1/market/orderbook/level2_100?symbol=BTC-USDT",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::LATOKEN:
            return {ex, "wss://api.latoken.com/stomp", "https://api.latoken.com/v2/book/BTC/USDT",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::LUNO:
            return {ex, "wss://ws.luno.com/api/1/stream/XBTZAR", "https://api.luno.com/api/1/orderbook_top?pair=XBTZAR",
                    "", "BTC/ZAR", true, false, 1, 0.002};
        case Exchange::MERCADO:
            return {ex, "", "https://api.mercadobitcoin.net/api/v4/btc/orderbook",
                    "", "BTC/BRL", false, false, 1, 0.003};
        case Exchange::NDAX:
            return {ex, "wss://api.ndax.io/ws", "https://api.ndax.io/api/getl2snapshot/1",
                    "", "BTC/CAD", true, false, 1, 0.002};
        case Exchange::NOVADAX:
            return {ex, "wss://api.novadax.com/websocket", "https://api.novadax.com/v1/market/depth?symbol=BTC_BRL&limit=50",
                    "", "BTC/BRL", true, false, 1, 0.002};
        case Exchange::OCEANEX:
            return {ex, "wss://ws.oceanex.pro/ws", "https://api.oceanex.pro/v1/order_book?market=btcusdt",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::OXFUN:
            return {ex, "wss://api.ox.fun/v1/ws", "https://api.ox.fun/v1/depth",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::P2B:
            return {ex, "wss://wsapi.p2pb2b.com", "https://api.p2pb2b.com/api/v2/public/book?market=BTC_USDT",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::PAYMIUM:
            return {ex, "", "https://paymium.com/api/v1/data/eur/depth",
                    "", "BTC/EUR", false, false, 1, 0.005};
        case Exchange::PROBIT:
            return {ex, "wss://api.probit.com/api/exchange/v1/ws", "https://api.probit.com/api/exchange/v1/order_book?market_id=BTC-USDT",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::TIMEX:
            return {ex, "wss://plasma-relay.timex.io", "https://plasma-relay.timex.io/public/book/BTCUSDT",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::TOKOCRYPTO:
            return {ex, "wss://stream.tokocrypto.com/ws", "https://www.tokocrypto.com/open/v1/market/depth",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::UPBIT:
            return {ex, "wss://api.upbit.com/websocket/v1", "https://api.upbit.com/v1/orderbook?markets=KRW-BTC",
                    "", "BTC/KRW", true, false, 1, 0.002};
        case Exchange::WAVESEXCHANGE:
            return {ex, "wss://matcher.waves.exchange/api/ws", "https://matcher.waves.exchange/api/v1/orderbook/WAVES/BTC",
                    "", "BTC/WAVES", true, false, 1, 0.002};
        case Exchange::WOO:
            return {ex, "wss://wss.woo.org/ws/stream", "https://api.woo.org/v1/orderbook/SPOT_BTC_USDT",
                    "", "BTC/USDT", true, false, 1, 0.002};
        case Exchange::YOBIT:
            return {ex, "", "https://yobit.net/api/3/depth/btc_usdt",
                    "", "BTC/USDT", false, false, 1, 0.002};
        case Exchange::ZAIF:
            return {ex, "wss://ws.zaif.jp/stream", "https://api.zaif.jp/api/1/depth/btc_jpy",
                    "", "BTC/JPY", true, false, 1, 0.002};
        case Exchange::ZONDA:
            return {ex, "wss://api.zonda.exchange/websocket/", "https://api.zonda.exchange/rest/trading/orderbook/BTC-PLN",
                    "", "BTC/PLN", true, false, 1, 0.002};

        default:
            return {Exchange::COUNT, "", "", "", "", false, false, 1, 0.005};
    }
}

// Legacy function for compatibility
inline const ExchangeConfig get_config(Exchange ex) {
    return get_exchange_config(ex);
}

// ============================================================================
// PRICE LEVEL
// ============================================================================

// Cache-line aligned for minimal false sharing (64 bytes on most CPUs)
struct alignas(16) PriceLevel {
    double price;
    double volume;

    PriceLevel() : price(0.0), volume(0.0) {}
    PriceLevel(double p, double v) : price(p), volume(v) {}
};

// ============================================================================
// ORDER BOOK
// ============================================================================

// Maximum levels to store (50 required for deterministic trading)
constexpr size_t MAX_BOOK_LEVELS = 100;

struct OrderBook {
    std::vector<PriceLevel> bids;  // Sorted by price DESCENDING (best bid first)
    std::vector<PriceLevel> asks;  // Sorted by price ASCENDING (best ask first)
    std::chrono::steady_clock::time_point timestamp;
    uint64_t sequence{0};  // For change detection (atomicity handled by cache mutex)

    OrderBook() {
        bids.reserve(MAX_BOOK_LEVELS);
        asks.reserve(MAX_BOOK_LEVELS);
    }

    // Allow copy and move (needed for cache operations)
    OrderBook(const OrderBook&) = default;
    OrderBook& operator=(const OrderBook&) = default;
    OrderBook(OrderBook&&) = default;
    OrderBook& operator=(OrderBook&&) = default;

    // Check if book has valid data
    bool is_valid() const {
        return !bids.empty() && !asks.empty();
    }

    // Best prices
    double best_bid() const {
        return bids.empty() ? 0.0 : bids[0].price;
    }

    double best_ask() const {
        return asks.empty() ? 0.0 : asks[0].price;
    }

    // Spread calculation
    double spread() const {
        return best_ask() - best_bid();
    }

    double spread_pct() const {
        double bid = best_bid();
        if (bid <= 0.0) return 0.0;
        return (best_ask() - bid) / bid * 100.0;
    }

    // Mid price
    double mid_price() const {
        double bid = best_bid();
        double ask = best_ask();
        if (bid <= 0.0 || ask <= 0.0) return 0.0;
        return (bid + ask) / 2.0;
    }

    // Total depth on each side
    double total_bid_depth(size_t max_levels = 50) const {
        double total = 0.0;
        size_t count = std::min(max_levels, bids.size());
        for (size_t i = 0; i < count; ++i) {
            total += bids[i].volume;
        }
        return total;
    }

    double total_ask_depth(size_t max_levels = 50) const {
        double total = 0.0;
        size_t count = std::min(max_levels, asks.size());
        for (size_t i = 0; i < count; ++i) {
            total += asks[i].volume;
        }
        return total;
    }

    // Age in milliseconds
    int64_t age_ms() const {
        auto now = std::chrono::steady_clock::now();
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            now - timestamp).count();
    }

    // Clear and reset
    void clear() {
        bids.clear();
        asks.clear();
        timestamp = std::chrono::steady_clock::time_point{};
    }
};

// ============================================================================
// INSTRUMENT DATA - All fields for any instrument type
// ============================================================================

struct InstrumentData {
    InstrumentType type = InstrumentType::SPOT;
    OrderBook book;

    // Common fields
    double last_price = 0.0;
    double volume_24h = 0.0;
    std::chrono::steady_clock::time_point timestamp;
    uint64_t sequence = 0;  // For change detection

    // PERPETUAL + INVERSE + FUTURES
    double mark_price = 0.0;
    double index_price = 0.0;

    // PERPETUAL + INVERSE
    double funding_rate = 0.0;          // Current funding rate (per 8 hours)
    int64_t next_funding_ts = 0;        // Next funding timestamp (ms)
    double predicted_funding = 0.0;     // Predicted next funding

    // FUTURES
    int64_t expiration_ts = 0;          // Expiration timestamp (ms)
    double basis = 0.0;                 // mark_price - index_price
    double basis_rate = 0.0;            // Annualized basis rate

    // OPTIONS
    double strike = 0.0;                // Strike price
    double implied_vol = 0.0;           // IV percentage
    bool is_call = true;                // true = call, false = put
    double delta = 0.0;                 // -1 to 1
    double gamma = 0.0;                 // Rate of delta change
    double theta = 0.0;                 // Time decay (per day)
    double vega = 0.0;                  // IV sensitivity
    double rho = 0.0;                   // Interest rate sensitivity
    double underlying_price = 0.0;      // Current underlying price
    double time_to_expiry = 0.0;        // Years to expiry

    // MARGIN
    double interest_rate_long = 0.0;    // Hourly interest for longs
    double interest_rate_short = 0.0;   // Hourly interest for shorts
    double max_leverage = 1.0;          // Maximum allowed leverage
    double maintenance_margin = 0.0;    // Maintenance margin ratio

    // INVERSE
    double contract_size = 1.0;         // BTC per contract
    double contract_value = 0.0;        // USD value per contract

    // LEVERAGED TOKEN
    double nav = 0.0;                   // Net Asset Value
    double real_leverage = 0.0;         // Current actual leverage
    double target_leverage = 3.0;       // Target leverage (e.g., 3x)
    int64_t rebalance_ts = 0;           // Last rebalance timestamp
    double basket = 0.0;                // Tokens in circulation

    // Validation
    bool is_valid() const {
        return book.is_valid() && last_price > 0;
    }

    // Age check
    int64_t age_ms() const {
        auto now = std::chrono::steady_clock::now();
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            now - timestamp).count();
    }

    // Get best bid/ask from book
    double best_bid() const { return book.best_bid(); }
    double best_ask() const { return book.best_ask(); }
    double spread_pct() const { return book.spread_pct(); }
};

// ============================================================================
// INSTRUMENT CONFIG - Per-instrument symbol configuration
// ============================================================================

struct InstrumentConfig {
    const char* symbol;                 // Trading symbol
    const char* orderbook_url;          // REST endpoint for order book
    const char* ws_channel;             // WebSocket channel
    bool available;                     // Is this instrument available?
};

// ============================================================================
// EXCHANGE INSTRUMENTS - All instruments for an exchange
// ============================================================================

struct ExchangeInstruments {
    Exchange id;
    uint8_t supported;                  // Bitfield of supported instruments

    InstrumentConfig spot;
    InstrumentConfig margin;
    InstrumentConfig perpetual;
    InstrumentConfig futures;
    InstrumentConfig options;
    InstrumentConfig inverse;
    InstrumentConfig leveraged_token;

    // Check if instrument is supported
    bool has(InstrumentType type) const {
        return supports_instrument(supported, type);
    }

    // Get config for instrument type
    const InstrumentConfig& get(InstrumentType type) const {
        switch (type) {
            case InstrumentType::SPOT: return spot;
            case InstrumentType::MARGIN: return margin;
            case InstrumentType::PERPETUAL: return perpetual;
            case InstrumentType::FUTURES: return futures;
            case InstrumentType::OPTIONS: return options;
            case InstrumentType::INVERSE: return inverse;
            case InstrumentType::LEVERAGED_TOKEN: return leveraged_token;
            default: return spot;
        }
    }
};

// ============================================================================
// PRICE IMPACT RESULT
// ============================================================================

struct PriceImpact {
    double start_price = 0.0;      // Price before execution
    double end_price = 0.0;        // Price after eating through levels
    double vwap = 0.0;             // Volume-Weighted Average Price
    double price_drop_pct = 0.0;   // Percentage drop (positive for sells)
    double volume_filled = 0.0;    // BTC actually fillable
    double volume_remaining = 0.0; // BTC that couldn't be filled
    double total_cost = 0.0;       // Total USD value
    int levels_eaten = 0;          // Number of price levels consumed

    // Check if trade would be profitable
    // Impact must be > 2x fees for guaranteed profit
    bool is_profitable(double fees_pct, double safety_multiple = 2.0) const {
        return std::abs(price_drop_pct) > (fees_pct * safety_multiple);
    }

    // Expected profit after fees
    double expected_profit_pct(double fees_pct) const {
        return std::abs(price_drop_pct) - fees_pct;
    }

    // Leveraged return
    double leveraged_return(double fees_pct, int leverage) const {
        double net = expected_profit_pct(fees_pct);
        return net > 0 ? net * leverage : 0.0;
    }
};

// ============================================================================
// BLOCKCHAIN SIGNAL
// ============================================================================

struct BlockchainSignal {
    std::string exchange;           // Exchange name (lowercase)
    bool is_inflow = false;         // true = deposit (SHORT), false = withdrawal (LONG)
    double btc_amount = 0.0;        // Amount detected
    int64_t latency_ns = 0;         // Detection latency in nanoseconds
    std::chrono::steady_clock::time_point timestamp;

    // Direction for trading
    bool is_short() const { return is_inflow; }
    bool is_long() const { return !is_inflow; }
};

// ============================================================================
// TRADE DECISION
// ============================================================================

struct TradeDecision {
    bool should_trade = false;      // Whether to execute
    bool is_short = false;          // Direction (true = SHORT, false = LONG)
    Exchange exchange = Exchange::COUNT;
    double entry_price = 0.0;
    double exit_price = 0.0;
    PriceImpact impact;
    std::string reason;             // Explanation (trade or skip reason)
    int64_t processing_ns = 0;      // Time to compute this decision

    // Leverage for this exchange
    int leverage() const {
        if (exchange == Exchange::COUNT) return 1;
        return get_exchange_config(exchange).max_leverage;
    }

    // Expected return with leverage
    double expected_return(double fees_pct = 0.10) const {
        return impact.leveraged_return(fees_pct, leverage());
    }
};

// ============================================================================
// TRADING CONFIGURATION
// ============================================================================

struct TradingConfig {
    double min_deposit_btc = 5.0;          // Minimum BTC to trigger trade
    double min_impact_multiple = 2.0;      // Impact must be 2x fees
    double fees_pct = 0.10;                // Round-trip fees (0.1%)
    double take_profit_ratio = 0.8;        // Exit at 80% of impact
    int max_book_age_ms = 5000;            // Maximum acceptable book staleness

    // Minimum required impact percentage
    double min_impact_pct() const {
        return fees_pct * min_impact_multiple;
    }
};

// ============================================================================
// EXCHANGE COUNT HELPERS
// ============================================================================

constexpr size_t TOTAL_EXCHANGES = static_cast<size_t>(Exchange::COUNT);
constexpr size_t PERPETUAL_EXCHANGES = 58;  // First 58 have perpetuals
constexpr size_t SPOT_ONLY_EXCHANGES = TOTAL_EXCHANGES - PERPETUAL_EXCHANGES;
constexpr size_t TOTAL_INSTRUMENTS = static_cast<size_t>(InstrumentType::INST_COUNT);

// ============================================================================
// GET EXCHANGE INSTRUMENTS - Full config for each exchange
// ============================================================================

inline ExchangeInstruments get_exchange_instruments(Exchange ex) {
    // Default empty config
    InstrumentConfig empty = {"", "", "", false};

    switch (ex) {
        // ============ TIER 1: FULL DERIVATIVES ============
        case Exchange::OKX:
            return {ex, INST_SPOT | INST_MARGIN | INST_PERPETUAL | INST_FUTURES | INST_OPTIONS | INST_INVERSE,
                {"BTC-USDT", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT&sz=50", "books5", true},
                {"BTC-USDT", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT&sz=50", "books5", true},
                {"BTC-USDT-SWAP", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT-SWAP&sz=50", "books5", true},
                {"BTC-USDT-250328", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT-250328&sz=50", "books5", true},
                {"BTC-USD-250328-100000-C", "https://www.okx.com/api/v5/market/books?instId=BTC-USD-250328-100000-C&sz=50", "books5", true},
                {"BTC-USD-SWAP", "https://www.okx.com/api/v5/market/books?instId=BTC-USD-SWAP&sz=50", "books5", true},
                empty};

        case Exchange::BYBIT:
            return {ex, INST_SPOT | INST_PERPETUAL | INST_FUTURES | INST_OPTIONS | INST_INVERSE,
                {"BTCUSDT", "https://api.bybit.com/v5/market/orderbook?category=spot&symbol=BTCUSDT&limit=50", "orderbook.50.BTCUSDT", true},
                empty,
                {"BTCUSDT", "https://api.bybit.com/v5/market/orderbook?category=linear&symbol=BTCUSDT&limit=50", "orderbook.50.BTCUSDT", true},
                {"BTCUSDT-28MAR25", "https://api.bybit.com/v5/market/orderbook?category=linear&symbol=BTCUSDT-28MAR25&limit=50", "orderbook.50", true},
                {"BTC-28MAR25-100000-C", "https://api.bybit.com/v5/market/orderbook?category=option&symbol=BTC-28MAR25-100000-C&limit=50", "orderbook", true},
                {"BTCUSD", "https://api.bybit.com/v5/market/orderbook?category=inverse&symbol=BTCUSD&limit=50", "orderbook.50.BTCUSD", true},
                empty};

        case Exchange::DERIBIT:
            return {ex, INST_PERPETUAL | INST_FUTURES | INST_OPTIONS | INST_INVERSE,
                empty, empty,
                {"BTC-PERPETUAL", "https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-PERPETUAL&depth=50", "book.BTC-PERPETUAL.100.1.100ms", true},
                {"BTC-28MAR25", "https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-28MAR25&depth=50", "book.BTC-28MAR25.100.1.100ms", true},
                {"BTC-28MAR25-100000-C", "https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-28MAR25-100000-C&depth=50", "book.option", true},
                {"BTC-PERPETUAL", "https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-PERPETUAL&depth=50", "book.BTC-PERPETUAL.100.1.100ms", true},
                empty};

        case Exchange::GATE:
        case Exchange::GATEIO:
            return {ex, INST_SPOT | INST_MARGIN | INST_PERPETUAL | INST_FUTURES | INST_OPTIONS | INST_LEVERAGED_TOKEN,
                {"BTC_USDT", "https://api.gateio.ws/api/v4/spot/order_book?currency_pair=BTC_USDT&limit=50", "spot.order_book", true},
                {"BTC_USDT", "https://api.gateio.ws/api/v4/margin/order_book?currency_pair=BTC_USDT&limit=50", "margin.order_book", true},
                {"BTC_USDT", "https://api.gateio.ws/api/v4/futures/usdt/order_book?contract=BTC_USDT&limit=50", "futures.order_book", true},
                {"BTC_USDT_20250328", "https://api.gateio.ws/api/v4/delivery/usdt/order_book?contract=BTC_USDT_20250328&limit=50", "delivery.order_book", true},
                {"BTC_USDT-20250328-100000-C", "https://api.gateio.ws/api/v4/options/order_book", "options.order_book", true},
                empty,
                {"BTC3L_USDT", "https://api.gateio.ws/api/v4/spot/order_book?currency_pair=BTC3L_USDT&limit=50", "spot.order_book", true}};

        // ============ TIER 2: PERPETUALS + FUTURES ============
        case Exchange::BINANCE:
            return {ex, INST_SPOT | INST_MARGIN | INST_PERPETUAL | INST_FUTURES | INST_INVERSE | INST_LEVERAGED_TOKEN,
                {"BTCUSDT", "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=100", "btcusdt@depth@100ms", true},
                {"BTCUSDT", "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=100", "btcusdt@depth@100ms", true},
                {"BTCUSDT", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=100", "btcusdt@depth@100ms", true},
                {"BTCUSDT_250328", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT_250328&limit=100", "btcusdt_250328@depth@100ms", true},
                empty,
                {"BTCUSD_PERP", "https://dapi.binance.com/dapi/v1/depth?symbol=BTCUSD_PERP&limit=100", "btcusd_perp@depth@100ms", true},
                {"BTCUP", "https://api.binance.com/api/v3/depth?symbol=BTCUPUSDT&limit=100", "btcupusdt@depth@100ms", true}};

        case Exchange::BINANCECOINM:
            return {ex, INST_PERPETUAL | INST_FUTURES | INST_INVERSE,
                empty, empty,
                {"BTCUSD_PERP", "https://dapi.binance.com/dapi/v1/depth?symbol=BTCUSD_PERP&limit=100", "btcusd_perp@depth@100ms", true},
                {"BTCUSD_250328", "https://dapi.binance.com/dapi/v1/depth?symbol=BTCUSD_250328&limit=100", "btcusd_250328@depth@100ms", true},
                empty,
                {"BTCUSD_PERP", "https://dapi.binance.com/dapi/v1/depth?symbol=BTCUSD_PERP&limit=100", "btcusd_perp@depth@100ms", true},
                empty};

        case Exchange::BINANCEUSDM:
            return {ex, INST_PERPETUAL | INST_FUTURES,
                empty, empty,
                {"BTCUSDT", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=100", "btcusdt@depth@100ms", true},
                {"BTCUSDT_250328", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT_250328&limit=100", "btcusdt_250328@depth@100ms", true},
                empty, empty, empty};

        case Exchange::BITGET:
            return {ex, INST_SPOT | INST_MARGIN | INST_PERPETUAL | INST_FUTURES,
                {"BTCUSDT", "https://api.bitget.com/api/v2/spot/market/orderbook?symbol=BTCUSDT&limit=50", "orderbook", true},
                {"BTCUSDT", "https://api.bitget.com/api/v2/spot/market/orderbook?symbol=BTCUSDT&limit=50", "orderbook", true},
                {"BTCUSDT_UMCBL", "https://api.bitget.com/api/v2/mix/market/depth?symbol=BTCUSDT&productType=USDT-FUTURES&limit=50", "orderbook", true},
                {"BTCUSDT_DMCBL", "https://api.bitget.com/api/v2/mix/market/depth?symbol=BTCUSDT&productType=USDT-FUTURES&limit=50", "orderbook", true},
                empty, empty, empty};

        case Exchange::MEXC:
            return {ex, INST_SPOT | INST_MARGIN | INST_PERPETUAL | INST_FUTURES | INST_LEVERAGED_TOKEN,
                {"BTCUSDT", "https://api.mexc.com/api/v3/depth?symbol=BTCUSDT&limit=100", "spot@depth", true},
                {"BTCUSDT", "https://api.mexc.com/api/v3/depth?symbol=BTCUSDT&limit=100", "spot@depth", true},
                {"BTC_USDT", "https://contract.mexc.com/api/v1/contract/depth/BTC_USDT", "contract@depth", true},
                {"BTC_USDT", "https://contract.mexc.com/api/v1/contract/depth/BTC_USDT", "contract@depth", true},
                empty, empty,
                {"BTC3L_USDT", "https://api.mexc.com/api/v3/depth?symbol=BTC3LUSDT&limit=100", "spot@depth", true}};

        case Exchange::HTX:
        case Exchange::HUOBI:
            return {ex, INST_SPOT | INST_MARGIN | INST_PERPETUAL | INST_FUTURES | INST_INVERSE,
                {"btcusdt", "https://api.huobi.pro/market/depth?symbol=btcusdt&type=step0&depth=50", "market.btcusdt.depth.step0", true},
                {"btcusdt", "https://api.huobi.pro/market/depth?symbol=btcusdt&type=step0&depth=50", "market.btcusdt.depth.step0", true},
                {"BTC-USDT", "https://api.hbdm.com/linear-swap-ex/market/depth?contract_code=BTC-USDT&type=step0", "market.BTC-USDT.depth.step0", true},
                {"BTC_CQ", "https://api.hbdm.com/market/depth?symbol=BTC_CQ&type=step0", "market.BTC_CQ.depth.step0", true},
                empty,
                {"BTC-USD", "https://api.hbdm.com/swap-ex/market/depth?contract_code=BTC-USD&type=step0", "market.BTC-USD.depth.step0", true},
                empty};

        case Exchange::BITMEX:
            return {ex, INST_PERPETUAL | INST_FUTURES | INST_INVERSE,
                empty, empty,
                {"XBTUSD", "https://www.bitmex.com/api/v1/orderBook/L2?symbol=XBTUSD&depth=50", "orderBookL2:XBTUSD", true},
                {"XBTM25", "https://www.bitmex.com/api/v1/orderBook/L2?symbol=XBTM25&depth=50", "orderBookL2:XBTM25", true},
                empty,
                {"XBTUSD", "https://www.bitmex.com/api/v1/orderBook/L2?symbol=XBTUSD&depth=50", "orderBookL2:XBTUSD", true},
                empty};

        case Exchange::KRAKENFUTURES:
            return {ex, INST_PERPETUAL | INST_FUTURES | INST_INVERSE,
                empty, empty,
                {"PI_XBTUSD", "https://futures.kraken.com/derivatives/api/v3/orderbook?symbol=PI_XBTUSD", "book", true},
                {"FI_XBTUSD_250328", "https://futures.kraken.com/derivatives/api/v3/orderbook?symbol=FI_XBTUSD_250328", "book", true},
                empty,
                {"PI_XBTUSD", "https://futures.kraken.com/derivatives/api/v3/orderbook?symbol=PI_XBTUSD", "book", true},
                empty};

        case Exchange::KUCOINFUTURES:
            return {ex, INST_PERPETUAL | INST_FUTURES | INST_INVERSE,
                empty, empty,
                {"XBTUSDTM", "https://api-futures.kucoin.com/api/v1/level2/snapshot?symbol=XBTUSDTM", "level2", true},
                {"XBTUSDTM", "https://api-futures.kucoin.com/api/v1/level2/snapshot?symbol=XBTUSDTM", "level2", true},
                empty,
                {"XBTUSDM", "https://api-futures.kucoin.com/api/v1/level2/snapshot?symbol=XBTUSDM", "level2", true},
                empty};

        case Exchange::PHEMEX:
            return {ex, INST_SPOT | INST_PERPETUAL | INST_FUTURES | INST_INVERSE,
                {"sBTCUSDT", "https://api.phemex.com/md/orderbook?symbol=sBTCUSDT", "orderbook.sBTCUSDT", true},
                empty,
                {"BTCUSD", "https://api.phemex.com/md/orderbook?symbol=BTCUSD", "orderbook.BTCUSD", true},
                {"BTCUSD", "https://api.phemex.com/md/orderbook?symbol=BTCUSD", "orderbook.BTCUSD", true},
                empty,
                {"BTCUSD", "https://api.phemex.com/md/orderbook?symbol=BTCUSD", "orderbook.BTCUSD", true},
                empty};

        // ============ TIER 3: PERPETUALS ONLY ============
        case Exchange::HYPERLIQUID:
            return {ex, INST_PERPETUAL,
                empty, empty,
                {"BTC", "https://api.hyperliquid.xyz/info", "l2Book", true},
                empty, empty, empty, empty};

        case Exchange::DYDX:
            return {ex, INST_PERPETUAL,
                empty, empty,
                {"BTC-USD", "https://api.dydx.exchange/v3/orderbook/BTC-USD", "v3_orderbook", true},
                empty, empty, empty, empty};

        // ============ TIER 4: SPOT + MARGIN ============
        case Exchange::KRAKEN:
            return {ex, INST_SPOT | INST_MARGIN,
                {"XXBTZUSD", "https://api.kraken.com/0/public/Depth?pair=XBTUSD&count=50", "book", true},
                {"XXBTZUSD", "https://api.kraken.com/0/public/Depth?pair=XBTUSD&count=50", "book", true},
                empty, empty, empty, empty, empty};

        case Exchange::KUCOIN:
            return {ex, INST_SPOT | INST_MARGIN | INST_LEVERAGED_TOKEN,
                {"BTC-USDT", "https://api.kucoin.com/api/v1/market/orderbook/level2_100?symbol=BTC-USDT", "level2", true},
                {"BTC-USDT", "https://api.kucoin.com/api/v1/market/orderbook/level2_100?symbol=BTC-USDT", "level2", true},
                empty, empty, empty, empty,
                {"BTC3L-USDT", "https://api.kucoin.com/api/v1/market/orderbook/level2_100?symbol=BTC3L-USDT", "level2", true}};

        // ============ TIER 5: SPOT ONLY (default) ============
        default: {
            // All other exchanges: spot only
            auto cfg = get_exchange_config(ex);
            return {ex, INST_SPOT,
                {cfg.spot_symbol, cfg.rest_url, "", cfg.has_websocket || strlen(cfg.rest_url) > 0},
                empty, empty, empty, empty, empty, empty};
        }
    }
}

} // namespace sovereign
