/**
 * Order Book Library - Compiled Components
 *
 * PURE DATA. NO MOCK. MATH NEVER LIES.
 *
 * This file contains any compiled (non-header-only) components of the
 * order book library. Most functionality is in the headers for
 * maximum inlining and optimization.
 */

#include "order_book_types.hpp"
#include "order_book_cache.hpp"
#include "impact_calculator.hpp"
#include "signal_handler.hpp"
#include "rest_client.hpp"

#ifdef HAS_WEBSOCKET
#include "websocket_manager.hpp"
#endif

namespace sovereign {

// ============================================================================
// VERSION INFO
// ============================================================================

const char* get_version() {
    return "1.0.0";
}

const char* get_build_info() {
#ifdef NDEBUG
    return "Release";
#else
    return "Debug";
#endif
}

// ============================================================================
// GLOBAL INITIALIZATION
// ============================================================================

static bool g_initialized = false;

bool initialize() {
    if (g_initialized) return true;

    // Initialize libcurl globally
    curl_global_init(CURL_GLOBAL_DEFAULT);

    g_initialized = true;
    return true;
}

void cleanup() {
    if (!g_initialized) return;

    curl_global_cleanup();
    g_initialized = false;
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

// Print exchange info
void print_exchange_info() {
    printf("\n=== SOVEREIGN ORDER BOOK SYSTEM ===\n");
    printf("Version: %s (%s)\n", get_version(), get_build_info());
    printf("\nSupported Exchanges:\n");

    for (size_t i = 0; i < static_cast<size_t>(Exchange::COUNT); ++i) {
        const auto cfg = get_exchange_config(static_cast<Exchange>(i));
        printf("  [%zu] %-10s | Leverage: %3dx | Fee: %.3f%% | WS: %s\n",
               i,
               EXCHANGE_NAMES[i],
               cfg.max_leverage,
               cfg.fee_pct * 100.0,
               cfg.has_websocket ? "Yes" : "No (REST)");
    }
    printf("\n");
}

// Benchmark impact calculation
void benchmark_impact_calculator(int iterations = 100000) {
    // Create test order book
    std::vector<PriceLevel> bids;
    for (int i = 0; i < 50; ++i) {
        bids.push_back({87000.0 - i * 10.0, 0.5 + i * 0.1});
    }

    // Warm up
    for (int i = 0; i < 1000; ++i) {
        auto impact = ImpactCalculator::calculate_sell_impact(10.0, bids);
        (void)impact;
    }

    // Benchmark
    auto start = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) {
        auto impact = ImpactCalculator::calculate_sell_impact(10.0, bids);
        (void)impact;
    }
    auto end = std::chrono::high_resolution_clock::now();

    auto total_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
    double avg_ns = static_cast<double>(total_ns) / iterations;

    printf("Impact Calculator Benchmark:\n");
    printf("  Iterations: %d\n", iterations);
    printf("  Total time: %ldns\n", total_ns);
    printf("  Average:    %.2fns per calculation\n", avg_ns);
    printf("  Rate:       %.2fM calculations/sec\n", 1000.0 / avg_ns);
}

} // namespace sovereign
