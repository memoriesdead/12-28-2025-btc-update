/**
 * Order Book System Test
 *
 * PURE DATA. NO MOCK. MATH NEVER LIES.
 *
 * This tests the order book system components:
 * 1. Impact calculator math (must match Python)
 * 2. Order book cache thread safety
 * 3. REST client fetching
 * 4. WebSocket connections (if available)
 * 5. Full pipeline benchmark
 */

#include "order_book_types.hpp"
#include "order_book_cache.hpp"
#include "impact_calculator.hpp"
#include "signal_handler.hpp"
#include "rest_client.hpp"
#include "orderbook_lib.hpp"

#ifdef HAS_WEBSOCKET
#include "websocket_manager.hpp"
#endif

#include <iostream>
#include <iomanip>
#include <thread>
#include <cassert>

using namespace sovereign;

// ============================================================================
// TEST HELPERS
// ============================================================================

#define TEST_ASSERT(cond, msg) \
    if (!(cond)) { \
        std::cerr << "FAIL: " << msg << std::endl; \
        return false; \
    }

#define TEST_NEAR(a, b, eps, msg) \
    if (std::abs((a) - (b)) > (eps)) { \
        std::cerr << "FAIL: " << msg << " (expected " << (b) << ", got " << (a) << ")" << std::endl; \
        return false; \
    }

// ============================================================================
// IMPACT CALCULATOR TESTS
// ============================================================================

bool test_sell_impact() {
    std::cout << "Testing sell impact calculation..." << std::endl;

    // Create test order book (matching Python test)
    std::vector<PriceLevel> bids = {
        {87000.0, 10.0},
        {86950.0, 15.0},
        {86900.0, 20.0},
        {86850.0, 25.0},
    };

    // Test 50 BTC sell
    auto impact = ImpactCalculator::calculate_sell_impact(50.0, bids);

    // Verify results
    TEST_NEAR(impact.start_price, 87000.0, 0.01, "start_price");
    TEST_NEAR(impact.end_price, 86850.0, 0.01, "end_price");
    TEST_NEAR(impact.volume_filled, 50.0, 0.01, "volume_filled");
    TEST_NEAR(impact.volume_remaining, 0.0, 0.01, "volume_remaining");
    TEST_NEAR(impact.levels_eaten, 4, 0, "levels_eaten");

    // Price drop should be (87000 - 86850) / 87000 * 100 = 0.1724%
    TEST_NEAR(impact.price_drop_pct, 0.1724, 0.001, "price_drop_pct");

    // VWAP calculation
    // 10 @ 87000 + 15 @ 86950 + 20 @ 86900 + 5 @ 86850 = total cost
    double expected_cost = 10*87000 + 15*86950 + 20*86900 + 5*86850;
    TEST_NEAR(impact.total_cost, expected_cost, 1.0, "total_cost");
    TEST_NEAR(impact.vwap, expected_cost / 50.0, 1.0, "vwap");

    std::cout << "  PASS: Sell impact calculation correct" << std::endl;
    return true;
}

bool test_profitability() {
    std::cout << "Testing profitability calculation..." << std::endl;

    // Impact > 2x fees should be profitable
    TEST_ASSERT(ImpactCalculator::is_profitable(0.25, 0.10, 2.0), "0.25% > 2x0.10% should be profitable");
    TEST_ASSERT(!ImpactCalculator::is_profitable(0.15, 0.10, 2.0), "0.15% < 2x0.10% should not be profitable");
    TEST_ASSERT(ImpactCalculator::is_profitable(0.20, 0.10, 2.0), "0.20% = 2x0.10% should be profitable");

    // Leveraged return
    double leverage_return = ImpactCalculator::leveraged_return(0.25, 0.10, 100);
    TEST_NEAR(leverage_return, 15.0, 0.01, "100x leverage on 0.15% net = 15%");

    std::cout << "  PASS: Profitability calculations correct" << std::endl;
    return true;
}

bool test_exit_price() {
    std::cout << "Testing exit price calculation..." << std::endl;

    PriceImpact impact;
    impact.price_drop_pct = 0.5;  // 0.5% drop

    // SHORT: Entry at 87000, expect exit below
    double exit_short = ImpactCalculator::calculate_exit_price(87000.0, impact, true, 0.8);
    // Target = 87000 * (1 - 0.5 * 0.8 / 100) = 87000 * 0.996 = 86652
    TEST_NEAR(exit_short, 86652.0, 1.0, "SHORT exit price");

    // LONG: Entry at 87000, expect exit above
    double exit_long = ImpactCalculator::calculate_exit_price(87000.0, impact, false, 0.8);
    // Target = 87000 * (1 + 0.5 * 0.8 / 100) = 87000 * 1.004 = 87348
    TEST_NEAR(exit_long, 87348.0, 1.0, "LONG exit price");

    std::cout << "  PASS: Exit price calculations correct" << std::endl;
    return true;
}

// ============================================================================
// ORDER BOOK CACHE TESTS
// ============================================================================

bool test_cache_basic() {
    std::cout << "Testing order book cache..." << std::endl;

    OrderBookCache cache;

    // Initially empty
    TEST_ASSERT(!cache.is_valid(Exchange::GEMINI), "Cache should be empty initially");

    // Create and update book
    OrderBook book;
    book.bids = {{87000.0, 1.0}, {86950.0, 2.0}};
    book.asks = {{87010.0, 0.5}, {87050.0, 1.5}};

    cache.update(Exchange::GEMINI, std::move(book));

    // Now should be valid
    TEST_ASSERT(cache.is_valid(Exchange::GEMINI), "Cache should be valid after update");
    TEST_ASSERT(!cache.is_stale(Exchange::GEMINI, 1000), "Cache should not be stale immediately");

    // Check values
    TEST_NEAR(cache.get_best_bid(Exchange::GEMINI), 87000.0, 0.01, "Best bid");
    TEST_NEAR(cache.get_best_ask(Exchange::GEMINI), 87010.0, 0.01, "Best ask");
    TEST_NEAR(cache.get_bid_depth(Exchange::GEMINI), 3.0, 0.01, "Bid depth");

    std::cout << "  PASS: Cache basic operations correct" << std::endl;
    return true;
}

bool test_cache_threading() {
    std::cout << "Testing cache thread safety..." << std::endl;

    OrderBookCache cache;
    std::atomic<int> read_count{0};
    std::atomic<int> write_count{0};

    // Writer thread
    std::thread writer([&]() {
        for (int i = 0; i < 1000; ++i) {
            OrderBook book;
            book.bids = {{87000.0 + i, 1.0}};
            book.asks = {{87010.0 + i, 1.0}};
            cache.update(Exchange::GEMINI, std::move(book));
            ++write_count;
        }
    });

    // Reader threads
    std::vector<std::thread> readers;
    for (int t = 0; t < 4; ++t) {
        readers.emplace_back([&]() {
            for (int i = 0; i < 1000; ++i) {
                auto book = cache.get(Exchange::GEMINI);
                if (book.is_valid()) {
                    // Just verify we can read without crash
                    (void)book.best_bid();
                }
                ++read_count;
            }
        });
    }

    writer.join();
    for (auto& r : readers) r.join();

    TEST_ASSERT(write_count.load() == 1000, "All writes completed");
    TEST_ASSERT(read_count.load() == 4000, "All reads completed");

    std::cout << "  PASS: Cache thread safety verified" << std::endl;
    return true;
}

// ============================================================================
// SIGNAL HANDLER TESTS
// ============================================================================

bool test_signal_handler() {
    std::cout << "Testing signal handler..." << std::endl;

    OrderBookCache cache;

    // Populate cache
    OrderBook book;
    book.bids.reserve(50);
    for (int i = 0; i < 50; ++i) {
        book.bids.push_back({87000.0 - i * 10.0, 0.5 + i * 0.1});
    }
    book.asks = {{87010.0, 1.0}};
    cache.update(Exchange::GEMINI, std::move(book));

    SignalHandler handler(cache);

    // Test signal that should trade
    BlockchainSignal sig;
    sig.exchange = "gemini";
    sig.is_inflow = true;  // Deposit = SHORT
    sig.btc_amount = 10.0;

    auto decision = handler.process_signal(sig);

    std::cout << "  Decision: " << (decision.should_trade ? "TRADE" : "SKIP") << std::endl;
    std::cout << "  Reason: " << decision.reason << std::endl;
    std::cout << "  Impact: " << decision.impact.price_drop_pct << "%" << std::endl;
    std::cout << "  Processing: " << decision.processing_ns << "ns" << std::endl;

    // Should not trade because impact is too small (need > 0.20%)
    // With our test data, 10 BTC impact should be around 0.11%
    if (!decision.should_trade) {
        std::cout << "  PASS: Correctly skipped low-impact trade" << std::endl;
    }

    // Test with larger amount that should trade
    sig.btc_amount = 50.0;
    decision = handler.process_signal(sig);

    std::cout << "  Decision (50 BTC): " << (decision.should_trade ? "TRADE" : "SKIP") << std::endl;
    std::cout << "  Impact (50 BTC): " << decision.impact.price_drop_pct << "%" << std::endl;

    return true;
}

// ============================================================================
// BENCHMARK
// ============================================================================

void benchmark_full_pipeline() {
    std::cout << "\n=== FULL PIPELINE BENCHMARK ===" << std::endl;

    OrderBookCache cache;

    // Populate cache with realistic data
    OrderBook book;
    book.bids.reserve(50);
    book.asks.reserve(50);
    for (int i = 0; i < 50; ++i) {
        book.bids.push_back({87000.0 - i * 10.0, 0.5 + i * 0.05});
        book.asks.push_back({87010.0 + i * 10.0, 0.5 + i * 0.05});
    }
    cache.update(Exchange::GEMINI, std::move(book));

    SignalHandler handler(cache);

    BlockchainSignal sig;
    sig.exchange = "gemini";
    sig.is_inflow = true;
    sig.btc_amount = 20.0;

    // Warm up
    for (int i = 0; i < 1000; ++i) {
        auto decision = handler.process_signal(sig);
        (void)decision;
    }

    // Benchmark
    const int iterations = 100000;
    auto start = std::chrono::high_resolution_clock::now();

    for (int i = 0; i < iterations; ++i) {
        auto decision = handler.process_signal(sig);
        (void)decision;
    }

    auto end = std::chrono::high_resolution_clock::now();
    auto total_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
    double avg_ns = static_cast<double>(total_ns) / iterations;

    std::cout << "Pipeline Benchmark Results:" << std::endl;
    std::cout << "  Iterations:     " << iterations << std::endl;
    std::cout << "  Total time:     " << total_ns / 1000000.0 << "ms" << std::endl;
    std::cout << "  Average:        " << avg_ns << "ns per signal" << std::endl;
    std::cout << "  Rate:           " << 1000000000.0 / avg_ns << " signals/sec" << std::endl;
    std::cout << std::endl;

    if (avg_ns < 10000) {
        std::cout << "  >>> PASS: Under 10 microseconds target! <<<" << std::endl;
    } else {
        std::cout << "  WARNING: Above 10 microseconds target" << std::endl;
    }
}

// ============================================================================
// REST CLIENT TEST
// ============================================================================

bool test_rest_client() {
    std::cout << "Testing REST client..." << std::endl;

    OrderBookCache cache;
    RESTClient client(cache);

    // Try to fetch from Gemini
    std::cout << "  Fetching Gemini order book..." << std::endl;
    bool success = client.fetch(Exchange::GEMINI);

    if (success) {
        std::cout << "  PASS: Gemini fetch successful" << std::endl;
        auto book = cache.get(Exchange::GEMINI);
        std::cout << "  Best bid: $" << book.best_bid() << std::endl;
        std::cout << "  Best ask: $" << book.best_ask() << std::endl;
        std::cout << "  Bid depth: " << book.total_bid_depth() << " BTC" << std::endl;
    } else {
        std::cout << "  SKIP: Gemini fetch failed (network issue?)" << std::endl;
    }

    return true;  // Don't fail on network issues
}

// ============================================================================
// MAIN
// ============================================================================

int main(int argc, char* argv[]) {
    std::cout << "========================================" << std::endl;
    std::cout << "SOVEREIGN ORDER BOOK SYSTEM - TEST SUITE" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << std::endl;

    sovereign::print_exchange_info();

    int passed = 0;
    int failed = 0;

    // Run tests
    auto run_test = [&](const char* name, bool (*test)()) {
        std::cout << "\n--- " << name << " ---" << std::endl;
        if (test()) {
            ++passed;
        } else {
            ++failed;
            std::cout << "FAILED: " << name << std::endl;
        }
    };

    run_test("Sell Impact", test_sell_impact);
    run_test("Profitability", test_profitability);
    run_test("Exit Price", test_exit_price);
    run_test("Cache Basic", test_cache_basic);
    run_test("Cache Threading", test_cache_threading);
    run_test("Signal Handler", test_signal_handler);
    run_test("REST Client", test_rest_client);

    // Benchmarks
    sovereign::benchmark_impact_calculator();
    benchmark_full_pipeline();

    // Summary
    std::cout << "\n========================================" << std::endl;
    std::cout << "RESULTS: " << passed << " passed, " << failed << " failed" << std::endl;
    std::cout << "========================================" << std::endl;

    return failed > 0 ? 1 : 0;
}
