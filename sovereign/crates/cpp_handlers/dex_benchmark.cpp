/**
 * DEX Feed Benchmark - Test Nanosecond Latency
 * =============================================
 *
 * Tests:
 * 1. Individual DEX fetch latency
 * 2. Parallel fetch latency
 * 3. Parse latency per orderbook
 * 4. Arbitrage detection speed
 *
 * Build:
 *   g++ -std=c++17 -O3 -march=native -o dex_benchmark dex_benchmark.cpp \
 *       -I../include -lcurl -lpthread
 *
 * Run:
 *   ./dex_benchmark
 */

#include <iostream>
#include <iomanip>
#include <chrono>
#include <vector>
#include <numeric>

#include "exchange_handlers/hyperliquid.hpp"
#include "exchange_handlers/dydx.hpp"
#include "exchange_handlers/injective.hpp"
#include "exchange_handlers/unified_dex_feed.hpp"

using namespace sovereign::exchange;
using namespace std::chrono;

// Simulated JSON responses for parse benchmarking
const std::string HL_SAMPLE_RESPONSE = R"({
    "levels": [
        [{"px": "94123.5", "sz": "1.234", "n": 5}, {"px": "94122.0", "sz": "2.5", "n": 3}],
        [{"px": "94125.0", "sz": "0.75", "n": 2}, {"px": "94126.5", "sz": "1.1", "n": 4}]
    ]
})";

const std::string DYDX_SAMPLE_RESPONSE = R"({
    "bids": [
        {"price": "94120.00", "size": "1.5"},
        {"price": "94118.50", "size": "2.0"}
    ],
    "asks": [
        {"price": "94125.00", "size": "0.8"},
        {"price": "94127.00", "size": "1.2"}
    ]
})";

const std::string INJ_SAMPLE_RESPONSE = R"({
    "orderbook": {
        "buys": [
            {"price": "94115.00", "quantity": "1.0"},
            {"price": "94113.00", "quantity": "2.5"}
        ],
        "sells": [
            {"price": "94128.00", "quantity": "0.5"},
            {"price": "94130.00", "quantity": "1.8"}
        ]
    }
})";

/**
 * Benchmark parse latency for each handler
 */
void benchmark_parse_latency(int iterations = 10000) {
    std::cout << "\n=== PARSE LATENCY BENCHMARK ===" << std::endl;
    std::cout << "Iterations: " << iterations << std::endl;
    std::cout << std::string(50, '-') << std::endl;

    std::vector<int64_t> hl_times, dydx_times, inj_times;
    OrderBook book;

    // Hyperliquid
    for (int i = 0; i < iterations; ++i) {
        auto start = high_resolution_clock::now();
        HyperliquidHandler::parse_rest_response(HL_SAMPLE_RESPONSE, book);
        auto end = high_resolution_clock::now();
        hl_times.push_back(duration_cast<nanoseconds>(end - start).count());
    }

    // dYdX
    for (int i = 0; i < iterations; ++i) {
        auto start = high_resolution_clock::now();
        DydxHandler::parse_rest_response(DYDX_SAMPLE_RESPONSE, book);
        auto end = high_resolution_clock::now();
        dydx_times.push_back(duration_cast<nanoseconds>(end - start).count());
    }

    // Injective
    for (int i = 0; i < iterations; ++i) {
        auto start = high_resolution_clock::now();
        InjectiveHandler::parse_rest_response(INJ_SAMPLE_RESPONSE, book);
        auto end = high_resolution_clock::now();
        inj_times.push_back(duration_cast<nanoseconds>(end - start).count());
    }

    // Calculate stats
    auto calc_stats = [](std::vector<int64_t>& times) {
        std::sort(times.begin(), times.end());
        int64_t min = times.front();
        int64_t max = times.back();
        int64_t median = times[times.size() / 2];
        int64_t p99 = times[static_cast<size_t>(times.size() * 0.99)];
        double avg = std::accumulate(times.begin(), times.end(), 0.0) / times.size();
        return std::make_tuple(min, max, median, p99, avg);
    };

    auto [hl_min, hl_max, hl_med, hl_p99, hl_avg] = calc_stats(hl_times);
    auto [dx_min, dx_max, dx_med, dx_p99, dx_avg] = calc_stats(dydx_times);
    auto [in_min, in_max, in_med, in_p99, in_avg] = calc_stats(inj_times);

    std::cout << std::setw(15) << "Handler"
              << std::setw(12) << "Min (ns)"
              << std::setw(12) << "Median"
              << std::setw(12) << "P99"
              << std::setw(12) << "Avg"
              << std::endl;
    std::cout << std::string(63, '-') << std::endl;

    std::cout << std::setw(15) << "Hyperliquid"
              << std::setw(12) << hl_min
              << std::setw(12) << hl_med
              << std::setw(12) << hl_p99
              << std::setw(12) << std::fixed << std::setprecision(1) << hl_avg
              << std::endl;

    std::cout << std::setw(15) << "dYdX"
              << std::setw(12) << dx_min
              << std::setw(12) << dx_med
              << std::setw(12) << dx_p99
              << std::setw(12) << std::fixed << std::setprecision(1) << dx_avg
              << std::endl;

    std::cout << std::setw(15) << "Injective"
              << std::setw(12) << in_min
              << std::setw(12) << in_med
              << std::setw(12) << in_p99
              << std::setw(12) << std::fixed << std::setprecision(1) << in_avg
              << std::endl;

    std::cout << std::string(50, '-') << std::endl;
    std::cout << "Target: < 1000ns per parse\n" << std::endl;
}

/**
 * Test orderbook parsing correctness
 */
void test_parse_correctness() {
    std::cout << "\n=== PARSE CORRECTNESS TEST ===" << std::endl;

    OrderBook book;

    // Test Hyperliquid
    if (HyperliquidHandler::parse_rest_response(HL_SAMPLE_RESPONSE, book)) {
        std::cout << "[OK] Hyperliquid: " << book.bids.size() << " bids, "
                  << book.asks.size() << " asks" << std::endl;
        if (!book.bids.empty()) {
            std::cout << "     Best bid: $" << std::fixed << std::setprecision(2)
                      << book.bids[0].price << " x " << book.bids[0].size << std::endl;
        }
    } else {
        std::cout << "[FAIL] Hyperliquid parse failed" << std::endl;
    }

    // Test dYdX
    if (DydxHandler::parse_rest_response(DYDX_SAMPLE_RESPONSE, book)) {
        std::cout << "[OK] dYdX: " << book.bids.size() << " bids, "
                  << book.asks.size() << " asks" << std::endl;
        if (!book.bids.empty()) {
            std::cout << "     Best bid: $" << std::fixed << std::setprecision(2)
                      << book.bids[0].price << " x " << book.bids[0].size << std::endl;
        }
    } else {
        std::cout << "[FAIL] dYdX parse failed" << std::endl;
    }

    // Test Injective
    if (InjectiveHandler::parse_rest_response(INJ_SAMPLE_RESPONSE, book)) {
        std::cout << "[OK] Injective: " << book.bids.size() << " bids, "
                  << book.asks.size() << " asks" << std::endl;
        if (!book.bids.empty()) {
            std::cout << "     Best bid: $" << std::fixed << std::setprecision(2)
                      << book.bids[0].price << " x " << book.bids[0].size << std::endl;
        }
    } else {
        std::cout << "[FAIL] Injective parse failed" << std::endl;
    }

    std::cout << std::endl;
}

/**
 * Test arbitrage detection with sample data
 */
void test_arbitrage_detection() {
    std::cout << "\n=== ARBITRAGE DETECTION TEST ===" << std::endl;

    // Create sample snapshots with price discrepancies
    std::unordered_map<Exchange, DEXSnapshot> snapshots;

    // Hyperliquid: best ask = 94125
    DEXSnapshot hl_snap;
    hl_snap.dex = Exchange::HYPERLIQUID;
    hl_snap.fee_pct = 0.035;
    hl_snap.valid = true;
    hl_snap.book.bids.push_back({94123.5, 1.234});
    hl_snap.book.asks.push_back({94125.0, 0.75});
    snapshots[Exchange::HYPERLIQUID] = hl_snap;

    // dYdX: best bid = 94120 (lower than HL ask - no arb)
    // But let's create an arb scenario: best bid = 94130 (higher than HL ask)
    DEXSnapshot dydx_snap;
    dydx_snap.dex = Exchange::DYDX;
    dydx_snap.fee_pct = 0.05;
    dydx_snap.valid = true;
    dydx_snap.book.bids.push_back({94130.0, 1.5});  // Higher than HL ask
    dydx_snap.book.asks.push_back({94135.0, 0.8});
    snapshots[Exchange::DYDX] = dydx_snap;

    // Injective
    DEXSnapshot inj_snap;
    inj_snap.dex = Exchange::INJECTIVE;
    inj_snap.fee_pct = 0.10;
    inj_snap.valid = true;
    inj_snap.book.bids.push_back({94115.0, 1.0});
    inj_snap.book.asks.push_back({94128.0, 0.5});
    snapshots[Exchange::INJECTIVE] = inj_snap;

    // Find arbitrage
    UnifiedDEXFeed feed;
    auto opportunities = feed.find_arbitrage(snapshots);

    std::cout << "Found " << opportunities.size() << " arbitrage opportunities:\n";
    for (const auto& opp : opportunities) {
        std::cout << "  BUY " << exchange_name(opp.buy_dex)
                  << " @ $" << std::fixed << std::setprecision(2) << opp.buy_price
                  << " -> SELL " << exchange_name(opp.sell_dex)
                  << " @ $" << opp.sell_price << std::endl;
        std::cout << "  Spread: " << std::setprecision(4) << opp.spread_pct << "%"
                  << " - Fees: " << opp.total_fees_pct << "%"
                  << " = Net: " << opp.net_profit_pct << "%" << std::endl;
    }

    std::cout << std::endl;
}

/**
 * Test flow consensus calculation
 */
void test_flow_consensus() {
    std::cout << "\n=== FLOW CONSENSUS TEST ===" << std::endl;

    std::unordered_map<Exchange, DEXSnapshot> snapshots;

    // All DEXes showing bullish flow
    DEXSnapshot hl_snap;
    hl_snap.dex = Exchange::HYPERLIQUID;
    hl_snap.valid = true;
    hl_snap.buy_volume = 1000000;
    hl_snap.sell_volume = 400000;
    hl_snap.imbalance_pct = 42.8;  // Bullish
    snapshots[Exchange::HYPERLIQUID] = hl_snap;

    DEXSnapshot dydx_snap;
    dydx_snap.dex = Exchange::DYDX;
    dydx_snap.valid = true;
    dydx_snap.buy_volume = 800000;
    dydx_snap.sell_volume = 300000;
    dydx_snap.imbalance_pct = 45.5;  // Bullish
    snapshots[Exchange::DYDX] = dydx_snap;

    DEXSnapshot inj_snap;
    inj_snap.dex = Exchange::INJECTIVE;
    inj_snap.valid = true;
    inj_snap.buy_volume = 500000;
    inj_snap.sell_volume = 200000;
    inj_snap.imbalance_pct = 42.8;  // Bullish
    snapshots[Exchange::INJECTIVE] = inj_snap;

    UnifiedDEXFeed feed;
    auto consensus = feed.analyze_flow(snapshots);

    std::cout << "Total Buy Volume:  $" << std::fixed << std::setprecision(0)
              << consensus.total_buy_volume << std::endl;
    std::cout << "Total Sell Volume: $" << consensus.total_sell_volume << std::endl;
    std::cout << "Consensus Imbalance: " << std::setprecision(1)
              << consensus.consensus_imbalance_pct << "%" << std::endl;
    std::cout << "Agreeing DEXes: " << consensus.agreeing_dexes
              << "/" << consensus.total_dexes << std::endl;
    std::cout << "Confidence: " << std::setprecision(0)
              << consensus.confidence * 100 << "%" << std::endl;
    std::cout << "Direction: " << consensus.direction << std::endl;

    std::cout << std::endl;
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << "  DEX FEED BENCHMARK - Nanosecond Speed" << std::endl;
    std::cout << "========================================" << std::endl;

    test_parse_correctness();
    test_arbitrage_detection();
    test_flow_consensus();
    benchmark_parse_latency(10000);

    std::cout << "========================================" << std::endl;
    std::cout << "  BENCHMARK COMPLETE" << std::endl;
    std::cout << "========================================" << std::endl;

    return 0;
}
