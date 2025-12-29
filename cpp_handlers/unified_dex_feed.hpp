/**
 * Unified DEX Feed - Nanosecond Latency Pipeline
 * ================================================
 *
 * Cross-reference data from all DEX nodes.
 * Let the data speak. Follow the math.
 *
 * Sources:
 * 1. Hyperliquid (local node @ localhost:3001 or public API)
 * 2. dYdX v4 (local node @ localhost:26657 or indexer API)
 * 3. Injective (local node @ localhost:9090 or LCD API)
 *
 * Strategy:
 * - Get orderbook from each DEX in parallel
 * - Calculate order flow imbalance across all sources
 * - Find cross-DEX arbitrage opportunities
 * - Trade where math works (impact > 2 x total fees)
 *
 * Performance targets:
 * - Parse latency: < 1000ns per orderbook
 * - Total pipeline: < 10us for all DEXes
 */

#pragma once

#include "hyperliquid.hpp"
#include "dydx.hpp"
#include "injective.hpp"
#include "../rest_client.hpp"

#include <vector>
#include <unordered_map>
#include <atomic>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <chrono>
#include <functional>

namespace sovereign {
namespace exchange {

/**
 * DEX state snapshot with timing info
 */
struct DEXSnapshot {
    Exchange dex;
    OrderBook book;
    double buy_volume;
    double sell_volume;
    double imbalance_pct;
    double fee_pct;
    int64_t fetch_latency_ns;
    int64_t parse_latency_ns;
    bool valid;
    std::chrono::system_clock::time_point timestamp;
};

/**
 * Cross-DEX arbitrage opportunity
 */
struct ArbitrageOpportunity {
    Exchange buy_dex;
    Exchange sell_dex;
    double buy_price;
    double sell_price;
    double spread_pct;
    double total_fees_pct;
    double net_profit_pct;
    double size_available;
    bool profitable;
};

/**
 * Flow consensus across all DEXes
 */
struct FlowConsensus {
    double total_buy_volume;
    double total_sell_volume;
    double consensus_imbalance_pct;
    int agreeing_dexes;
    int total_dexes;
    double confidence;
    std::string direction;  // "long", "short", or "neutral"
};

/**
 * Unified DEX Feed - Thread-safe, lock-free where possible
 */
class UnifiedDEXFeed {
public:
    // Fee structure (in percent)
    static constexpr double FEE_HYPERLIQUID = 0.035;
    static constexpr double FEE_DYDX = 0.050;
    static constexpr double FEE_INJECTIVE = 0.100;

    UnifiedDEXFeed() : running_(false) {
        // Initialize REST clients for each DEX
        // Local nodes preferred, fallback to public APIs
    }

    ~UnifiedDEXFeed() {
        stop();
    }

    /**
     * Fetch all DEX snapshots in parallel.
     * Returns map of Exchange -> DEXSnapshot.
     */
    std::unordered_map<Exchange, DEXSnapshot> fetch_all(const std::string& coin = "BTC") {
        std::unordered_map<Exchange, DEXSnapshot> snapshots;
        std::mutex mtx;

        auto start = std::chrono::high_resolution_clock::now();

        // Parallel fetch from all DEXes
        std::vector<std::thread> threads;

        // Hyperliquid
        threads.emplace_back([&]() {
            auto snap = fetch_hyperliquid(coin);
            std::lock_guard<std::mutex> lock(mtx);
            snapshots[Exchange::HYPERLIQUID] = snap;
        });

        // dYdX
        threads.emplace_back([&]() {
            auto snap = fetch_dydx(coin);
            std::lock_guard<std::mutex> lock(mtx);
            snapshots[Exchange::DYDX] = snap;
        });

        // Injective
        threads.emplace_back([&]() {
            auto snap = fetch_injective(coin);
            std::lock_guard<std::mutex> lock(mtx);
            snapshots[Exchange::INJECTIVE] = snap;
        });

        // Wait for all to complete
        for (auto& t : threads) {
            if (t.joinable()) t.join();
        }

        auto end = std::chrono::high_resolution_clock::now();
        total_fetch_latency_ns_ = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

        return snapshots;
    }

    /**
     * Find arbitrage opportunities across DEXes.
     */
    std::vector<ArbitrageOpportunity> find_arbitrage(
        const std::unordered_map<Exchange, DEXSnapshot>& snapshots
    ) {
        std::vector<ArbitrageOpportunity> opportunities;

        // Compare all pairs of DEXes
        for (auto& [dex1, snap1] : snapshots) {
            if (!snap1.valid || snap1.book.asks.empty() || snap1.book.bids.empty()) continue;

            for (auto& [dex2, snap2] : snapshots) {
                if (dex1 == dex2) continue;
                if (!snap2.valid || snap2.book.asks.empty() || snap2.book.bids.empty()) continue;

                double buy_price = snap1.book.asks[0].price;
                double sell_price = snap2.book.bids[0].price;

                // Can we buy on dex1 and sell on dex2?
                if (buy_price < sell_price) {
                    double spread = (sell_price - buy_price) / buy_price * 100.0;
                    double total_fees = snap1.fee_pct + snap2.fee_pct;
                    double net_profit = spread - total_fees;

                    ArbitrageOpportunity opp;
                    opp.buy_dex = dex1;
                    opp.sell_dex = dex2;
                    opp.buy_price = buy_price;
                    opp.sell_price = sell_price;
                    opp.spread_pct = spread;
                    opp.total_fees_pct = total_fees;
                    opp.net_profit_pct = net_profit;
                    opp.size_available = std::min(snap1.book.asks[0].size, snap2.book.bids[0].size);
                    opp.profitable = net_profit > 0;

                    if (opp.profitable) {
                        opportunities.push_back(opp);
                    }
                }
            }
        }

        // Sort by profit descending
        std::sort(opportunities.begin(), opportunities.end(),
            [](const ArbitrageOpportunity& a, const ArbitrageOpportunity& b) {
                return a.net_profit_pct > b.net_profit_pct;
            });

        return opportunities;
    }

    /**
     * Analyze flow consensus across all DEXes.
     */
    FlowConsensus analyze_flow(const std::unordered_map<Exchange, DEXSnapshot>& snapshots) {
        FlowConsensus consensus;
        consensus.total_buy_volume = 0;
        consensus.total_sell_volume = 0;
        consensus.agreeing_dexes = 0;
        consensus.total_dexes = 0;

        for (auto& [dex, snap] : snapshots) {
            if (!snap.valid) continue;

            consensus.total_buy_volume += snap.buy_volume;
            consensus.total_sell_volume += snap.sell_volume;
            consensus.total_dexes++;
        }

        double total = consensus.total_buy_volume + consensus.total_sell_volume;
        if (total > 0) {
            consensus.consensus_imbalance_pct =
                (consensus.total_buy_volume - consensus.total_sell_volume) / total * 100.0;
        } else {
            consensus.consensus_imbalance_pct = 0;
        }

        // Count agreeing DEXes
        for (auto& [dex, snap] : snapshots) {
            if (!snap.valid) continue;

            if ((consensus.consensus_imbalance_pct > 0 && snap.imbalance_pct > 0) ||
                (consensus.consensus_imbalance_pct < 0 && snap.imbalance_pct < 0)) {
                consensus.agreeing_dexes++;
            }
        }

        consensus.confidence = consensus.total_dexes > 0 ?
            static_cast<double>(consensus.agreeing_dexes) / consensus.total_dexes : 0;

        // Determine direction
        if (std::abs(consensus.consensus_imbalance_pct) > 50 && consensus.confidence > 0.6) {
            consensus.direction = consensus.consensus_imbalance_pct > 0 ? "long" : "short";
        } else {
            consensus.direction = "neutral";
        }

        return consensus;
    }

    /**
     * Get the best price across all DEXes.
     */
    std::pair<double, Exchange> get_best_bid(const std::unordered_map<Exchange, DEXSnapshot>& snapshots) {
        double best_price = 0;
        Exchange best_dex = Exchange::UNKNOWN;

        for (auto& [dex, snap] : snapshots) {
            if (snap.valid && !snap.book.bids.empty()) {
                if (snap.book.bids[0].price > best_price) {
                    best_price = snap.book.bids[0].price;
                    best_dex = dex;
                }
            }
        }
        return {best_price, best_dex};
    }

    std::pair<double, Exchange> get_best_ask(const std::unordered_map<Exchange, DEXSnapshot>& snapshots) {
        double best_price = std::numeric_limits<double>::max();
        Exchange best_dex = Exchange::UNKNOWN;

        for (auto& [dex, snap] : snapshots) {
            if (snap.valid && !snap.book.asks.empty()) {
                if (snap.book.asks[0].price < best_price) {
                    best_price = snap.book.asks[0].price;
                    best_dex = dex;
                }
            }
        }
        return {best_price, best_dex};
    }

    /**
     * Get total pipeline latency in nanoseconds.
     */
    int64_t get_total_latency_ns() const {
        return total_fetch_latency_ns_;
    }

    /**
     * Start continuous monitoring with callback.
     */
    void start(std::function<void(const std::unordered_map<Exchange, DEXSnapshot>&)> callback,
               int interval_ms = 100) {
        running_ = true;
        monitor_thread_ = std::thread([this, callback, interval_ms]() {
            while (running_) {
                auto snapshots = fetch_all("BTC");
                callback(snapshots);
                std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
            }
        });
    }

    void stop() {
        running_ = false;
        if (monitor_thread_.joinable()) {
            monitor_thread_.join();
        }
    }

private:
    std::atomic<bool> running_;
    std::thread monitor_thread_;
    std::atomic<int64_t> total_fetch_latency_ns_{0};

    DEXSnapshot fetch_hyperliquid(const std::string& coin) {
        DEXSnapshot snap;
        snap.dex = Exchange::HYPERLIQUID;
        snap.fee_pct = FEE_HYPERLIQUID;
        snap.valid = false;

        auto start = std::chrono::high_resolution_clock::now();

        try {
            // Try local node first, fallback to public API
            std::string url = HyperliquidHandler::LOCAL_REST_URL;
            std::string body = HyperliquidHandler::get_orderbook_request(coin);

            // Use REST client to POST
            RestClient client;
            std::string response = client.post(url, body);

            if (response.empty()) {
                // Fallback to public API
                url = HyperliquidHandler::REST_URL;
                response = client.post(url, body);
            }

            if (!response.empty() && HyperliquidHandler::parse_rest_response(response, snap.book)) {
                snap.valid = true;
                snap.parse_latency_ns = snap.book.parse_latency_ns;

                // Get trades for flow
                std::string trades_body = HyperliquidHandler::get_trades_request(coin);
                std::string trades_response = client.post(url, trades_body);
                if (!trades_response.empty()) {
                    auto [buy, sell, imb] = HyperliquidHandler::parse_trades(trades_response);
                    snap.buy_volume = buy;
                    snap.sell_volume = sell;
                    snap.imbalance_pct = imb;
                }
            }
        } catch (...) {
            snap.valid = false;
        }

        auto end = std::chrono::high_resolution_clock::now();
        snap.fetch_latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        snap.timestamp = std::chrono::system_clock::now();

        return snap;
    }

    DEXSnapshot fetch_dydx(const std::string& coin) {
        DEXSnapshot snap;
        snap.dex = Exchange::DYDX;
        snap.fee_pct = FEE_DYDX;
        snap.valid = false;

        auto start = std::chrono::high_resolution_clock::now();

        try {
            RestClient client;
            std::string response = client.get(DydxHandler::REST_URL);

            if (!response.empty() && DydxHandler::parse_rest_response(response, snap.book)) {
                snap.valid = true;
                snap.parse_latency_ns = snap.book.parse_latency_ns;
            }
        } catch (...) {
            snap.valid = false;
        }

        auto end = std::chrono::high_resolution_clock::now();
        snap.fetch_latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        snap.timestamp = std::chrono::system_clock::now();

        return snap;
    }

    DEXSnapshot fetch_injective(const std::string& coin) {
        DEXSnapshot snap;
        snap.dex = Exchange::INJECTIVE;
        snap.fee_pct = FEE_INJECTIVE;
        snap.valid = false;

        auto start = std::chrono::high_resolution_clock::now();

        try {
            RestClient client;
            std::string url = InjectiveHandler::get_orderbook_url();
            std::string response = client.get(url);

            if (!response.empty() && InjectiveHandler::parse_rest_response(response, snap.book)) {
                snap.valid = true;
                snap.parse_latency_ns = snap.book.parse_latency_ns;

                // Get trades for flow
                std::string trades_url = InjectiveHandler::get_trades_url();
                std::string trades_response = client.get(trades_url);
                if (!trades_response.empty()) {
                    auto [buy, sell, imb] = InjectiveHandler::parse_trades(trades_response);
                    snap.buy_volume = buy;
                    snap.sell_volume = sell;
                    snap.imbalance_pct = imb;
                }
            }
        } catch (...) {
            snap.valid = false;
        }

        auto end = std::chrono::high_resolution_clock::now();
        snap.fetch_latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        snap.timestamp = std::chrono::system_clock::now();

        return snap;
    }
};

/**
 * Get exchange name as string
 */
inline const char* exchange_name(Exchange ex) {
    switch (ex) {
        case Exchange::HYPERLIQUID: return "Hyperliquid";
        case Exchange::DYDX: return "dYdX";
        case Exchange::INJECTIVE: return "Injective";
        default: return "Unknown";
    }
}

} // namespace exchange
} // namespace sovereign
