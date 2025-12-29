/**
 * DEX Feed Benchmark - Standalone Test (No Dependencies on Custom Types)
 * ======================================================================
 *
 * Tests nanosecond parse latency for Hyperliquid, dYdX, Injective.
 * Uses minimal custom types to avoid dependency issues.
 *
 * Build:
 *   g++ -std=c++17 -O3 -march=native -o dex_benchmark dex_benchmark_standalone.cpp -lpthread
 *
 * Run:
 *   ./dex_benchmark
 */

#include <iostream>
#include <iomanip>
#include <chrono>
#include <vector>
#include <numeric>
#include <string>
#include <cstdlib>
#include <tuple>
#include <algorithm>

// ============================================================================
// MINIMAL TYPES
// ============================================================================

struct PriceLevel {
    double price;
    double volume;
};

struct OrderBook {
    std::vector<PriceLevel> bids;
    std::vector<PriceLevel> asks;

    bool is_valid() const {
        return !bids.empty() && !asks.empty();
    }
};

constexpr size_t MAX_LEVELS = 50;

// ============================================================================
// HYPERLIQUID PARSER
// ============================================================================

namespace hyperliquid {

size_t find_matching_bracket(const std::string& s, size_t start) {
    if (start >= s.size() || s[start] != '[') return std::string::npos;
    int depth = 1;
    for (size_t i = start + 1; i < s.size(); ++i) {
        if (s[i] == '[') depth++;
        else if (s[i] == ']') {
            depth--;
            if (depth == 0) return i;
        }
    }
    return std::string::npos;
}

double parse_string_number(const std::string& s, size_t key_pos) {
    if (key_pos == std::string::npos) return 0.0;
    size_t colon = s.find(':', key_pos);
    if (colon == std::string::npos) return 0.0;
    size_t val_start = colon + 1;
    while (val_start < s.size() && (s[val_start] == ' ' || s[val_start] == '"')) val_start++;
    size_t val_end = val_start;
    while (val_end < s.size() && (isdigit(s[val_end]) || s[val_end] == '.' || s[val_end] == '-')) val_end++;
    if (val_end > val_start) {
        return std::strtod(s.substr(val_start, val_end - val_start).c_str(), nullptr);
    }
    return 0.0;
}

void parse_levels(const std::string& arr, std::vector<PriceLevel>& levels) {
    size_t pos = 0;
    while (pos < arr.size() && levels.size() < MAX_LEVELS) {
        size_t obj_start = arr.find('{', pos);
        if (obj_start == std::string::npos) break;
        size_t obj_end = arr.find('}', obj_start);
        if (obj_end == std::string::npos) break;
        std::string obj = arr.substr(obj_start, obj_end - obj_start + 1);
        double price = parse_string_number(obj, obj.find("\"px\""));
        double sz = parse_string_number(obj, obj.find("\"sz\""));
        if (price > 0.0 && sz > 0.0) {
            levels.push_back({price, sz});
        }
        pos = obj_end + 1;
    }
}

bool parse(const std::string& json, OrderBook& book) {
    book.bids.clear();
    book.asks.clear();

    size_t levels_pos = json.find("\"levels\"");
    if (levels_pos == std::string::npos) return false;

    size_t arr_start = json.find('[', levels_pos);
    if (arr_start == std::string::npos) return false;

    // Parse bids (first inner array)
    size_t bids_start = json.find('[', arr_start + 1);
    if (bids_start != std::string::npos) {
        size_t bids_end = find_matching_bracket(json, bids_start);
        if (bids_end != std::string::npos) {
            parse_levels(json.substr(bids_start, bids_end - bids_start + 1), book.bids);
        }

        // Parse asks (second inner array)
        size_t asks_start = json.find('[', bids_end + 1);
        if (asks_start != std::string::npos) {
            size_t asks_end = find_matching_bracket(json, asks_start);
            if (asks_end != std::string::npos) {
                parse_levels(json.substr(asks_start, asks_end - asks_start + 1), book.asks);
            }
        }
    }

    return book.is_valid();
}

} // namespace hyperliquid

// ============================================================================
// DYDX PARSER
// ============================================================================

namespace dydx {

double parse_string_number(const std::string& s, size_t key_pos) {
    if (key_pos == std::string::npos) return 0.0;
    size_t colon = s.find(':', key_pos);
    if (colon == std::string::npos) return 0.0;
    size_t val_start = colon + 1;
    while (val_start < s.size() && (s[val_start] == ' ' || s[val_start] == '"')) val_start++;
    size_t val_end = val_start;
    while (val_end < s.size() && (isdigit(s[val_end]) || s[val_end] == '.' || s[val_end] == '-')) val_end++;
    if (val_end > val_start) {
        return std::strtod(s.substr(val_start, val_end - val_start).c_str(), nullptr);
    }
    return 0.0;
}

size_t find_matching_bracket(const std::string& s, size_t start) {
    if (start >= s.size() || s[start] != '[') return std::string::npos;
    int depth = 1;
    for (size_t i = start + 1; i < s.size(); ++i) {
        if (s[i] == '[') depth++;
        else if (s[i] == ']') {
            depth--;
            if (depth == 0) return i;
        }
    }
    return std::string::npos;
}

void parse_levels(const std::string& arr, std::vector<PriceLevel>& levels) {
    size_t pos = 0;
    while (pos < arr.size() && levels.size() < MAX_LEVELS) {
        size_t obj_start = arr.find('{', pos);
        if (obj_start == std::string::npos) break;
        size_t obj_end = arr.find('}', obj_start);
        if (obj_end == std::string::npos) break;
        std::string obj = arr.substr(obj_start, obj_end - obj_start + 1);
        double price = parse_string_number(obj, obj.find("\"price\""));
        double size = parse_string_number(obj, obj.find("\"size\""));
        if (price > 0.0 && size > 0.0) {
            levels.push_back({price, size});
        }
        pos = obj_end + 1;
    }
}

bool parse(const std::string& json, OrderBook& book) {
    book.bids.clear();
    book.asks.clear();

    // Parse bids
    size_t bids_pos = json.find("\"bids\"");
    if (bids_pos != std::string::npos) {
        size_t arr_start = json.find('[', bids_pos);
        size_t arr_end = find_matching_bracket(json, arr_start);
        if (arr_start != std::string::npos && arr_end != std::string::npos) {
            parse_levels(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
        }
    }

    // Parse asks
    size_t asks_pos = json.find("\"asks\"");
    if (asks_pos != std::string::npos) {
        size_t arr_start = json.find('[', asks_pos);
        size_t arr_end = find_matching_bracket(json, arr_start);
        if (arr_start != std::string::npos && arr_end != std::string::npos) {
            parse_levels(json.substr(arr_start, arr_end - arr_start + 1), book.asks);
        }
    }

    return book.is_valid();
}

} // namespace dydx

// ============================================================================
// INJECTIVE PARSER
// ============================================================================

namespace injective {

double parse_string_number(const std::string& s, size_t key_pos) {
    if (key_pos == std::string::npos) return 0.0;
    size_t colon = s.find(':', key_pos);
    if (colon == std::string::npos) return 0.0;
    size_t val_start = colon + 1;
    while (val_start < s.size() && (s[val_start] == ' ' || s[val_start] == '"')) val_start++;
    size_t val_end = val_start;
    while (val_end < s.size() && (isdigit(s[val_end]) || s[val_end] == '.' || s[val_end] == '-')) val_end++;
    if (val_end > val_start) {
        return std::strtod(s.substr(val_start, val_end - val_start).c_str(), nullptr);
    }
    return 0.0;
}

size_t find_matching_bracket(const std::string& s, size_t start) {
    if (start >= s.size() || s[start] != '[') return std::string::npos;
    int depth = 1;
    for (size_t i = start + 1; i < s.size(); ++i) {
        if (s[i] == '[') depth++;
        else if (s[i] == ']') {
            depth--;
            if (depth == 0) return i;
        }
    }
    return std::string::npos;
}

void parse_levels(const std::string& arr, std::vector<PriceLevel>& levels) {
    size_t pos = 0;
    while (pos < arr.size() && levels.size() < MAX_LEVELS) {
        size_t obj_start = arr.find('{', pos);
        if (obj_start == std::string::npos) break;
        size_t obj_end = arr.find('}', obj_start);
        if (obj_end == std::string::npos) break;
        std::string obj = arr.substr(obj_start, obj_end - obj_start + 1);
        double price = parse_string_number(obj, obj.find("\"price\""));
        double qty = parse_string_number(obj, obj.find("\"quantity\""));
        if (price > 0.0 && qty > 0.0) {
            levels.push_back({price, qty});
        }
        pos = obj_end + 1;
    }
}

bool parse(const std::string& json, OrderBook& book) {
    book.bids.clear();
    book.asks.clear();

    // Parse buys (bids)
    size_t buys_pos = json.find("\"buys\"");
    if (buys_pos != std::string::npos) {
        size_t arr_start = json.find('[', buys_pos);
        size_t arr_end = find_matching_bracket(json, arr_start);
        if (arr_start != std::string::npos && arr_end != std::string::npos) {
            parse_levels(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
        }
    }

    // Parse sells (asks)
    size_t sells_pos = json.find("\"sells\"");
    if (sells_pos != std::string::npos) {
        size_t arr_start = json.find('[', sells_pos);
        size_t arr_end = find_matching_bracket(json, arr_start);
        if (arr_start != std::string::npos && arr_end != std::string::npos) {
            parse_levels(json.substr(arr_start, arr_end - arr_start + 1), book.asks);
        }
    }

    return book.is_valid();
}

} // namespace injective

// ============================================================================
// TEST DATA
// ============================================================================

const std::string HL_SAMPLE = R"({
    "levels": [
        [{"px": "94123.5", "sz": "1.234", "n": 5}, {"px": "94122.0", "sz": "2.5", "n": 3}],
        [{"px": "94125.0", "sz": "0.75", "n": 2}, {"px": "94126.5", "sz": "1.1", "n": 4}]
    ]
})";

const std::string DYDX_SAMPLE = R"({
    "bids": [
        {"price": "94120.00", "size": "1.5"},
        {"price": "94118.50", "size": "2.0"}
    ],
    "asks": [
        {"price": "94125.00", "size": "0.8"},
        {"price": "94127.00", "size": "1.2"}
    ]
})";

const std::string INJ_SAMPLE = R"({
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

// ============================================================================
// BENCHMARKS
// ============================================================================

void test_correctness() {
    std::cout << "\n=== PARSE CORRECTNESS TEST ===" << std::endl;

    OrderBook book;

    // Hyperliquid
    if (hyperliquid::parse(HL_SAMPLE, book)) {
        std::cout << "[OK] Hyperliquid: " << book.bids.size() << " bids, "
                  << book.asks.size() << " asks" << std::endl;
        if (!book.bids.empty()) {
            std::cout << "     Best bid: $" << std::fixed << std::setprecision(2)
                      << book.bids[0].price << " x " << book.bids[0].volume << std::endl;
        }
    } else {
        std::cout << "[FAIL] Hyperliquid" << std::endl;
    }

    // dYdX
    if (dydx::parse(DYDX_SAMPLE, book)) {
        std::cout << "[OK] dYdX: " << book.bids.size() << " bids, "
                  << book.asks.size() << " asks" << std::endl;
        if (!book.bids.empty()) {
            std::cout << "     Best bid: $" << std::fixed << std::setprecision(2)
                      << book.bids[0].price << " x " << book.bids[0].volume << std::endl;
        }
    } else {
        std::cout << "[FAIL] dYdX" << std::endl;
    }

    // Injective
    if (injective::parse(INJ_SAMPLE, book)) {
        std::cout << "[OK] Injective: " << book.bids.size() << " bids, "
                  << book.asks.size() << " asks" << std::endl;
        if (!book.bids.empty()) {
            std::cout << "     Best bid: $" << std::fixed << std::setprecision(2)
                      << book.bids[0].price << " x " << book.bids[0].volume << std::endl;
        }
    } else {
        std::cout << "[FAIL] Injective" << std::endl;
    }
}

void benchmark_latency(int iterations = 10000) {
    std::cout << "\n=== PARSE LATENCY BENCHMARK ===" << std::endl;
    std::cout << "Iterations: " << iterations << std::endl;
    std::cout << std::string(60, '-') << std::endl;

    using namespace std::chrono;
    std::vector<int64_t> hl_times, dydx_times, inj_times;
    OrderBook book;

    // Hyperliquid
    for (int i = 0; i < iterations; ++i) {
        auto start = high_resolution_clock::now();
        hyperliquid::parse(HL_SAMPLE, book);
        auto end = high_resolution_clock::now();
        hl_times.push_back(duration_cast<nanoseconds>(end - start).count());
    }

    // dYdX
    for (int i = 0; i < iterations; ++i) {
        auto start = high_resolution_clock::now();
        dydx::parse(DYDX_SAMPLE, book);
        auto end = high_resolution_clock::now();
        dydx_times.push_back(duration_cast<nanoseconds>(end - start).count());
    }

    // Injective
    for (int i = 0; i < iterations; ++i) {
        auto start = high_resolution_clock::now();
        injective::parse(INJ_SAMPLE, book);
        auto end = high_resolution_clock::now();
        inj_times.push_back(duration_cast<nanoseconds>(end - start).count());
    }

    // Stats calculation
    auto calc_stats = [](std::vector<int64_t>& times) {
        std::sort(times.begin(), times.end());
        int64_t min = times.front();
        int64_t median = times[times.size() / 2];
        int64_t p99 = times[static_cast<size_t>(times.size() * 0.99)];
        double avg = std::accumulate(times.begin(), times.end(), 0.0) / times.size();
        return std::make_tuple(min, median, p99, avg);
    };

    auto [hl_min, hl_med, hl_p99, hl_avg] = calc_stats(hl_times);
    auto [dx_min, dx_med, dx_p99, dx_avg] = calc_stats(dydx_times);
    auto [in_min, in_med, in_p99, in_avg] = calc_stats(inj_times);

    std::cout << std::setw(12) << "DEX"
              << std::setw(12) << "Min (ns)"
              << std::setw(12) << "Median"
              << std::setw(12) << "P99"
              << std::setw(12) << "Avg"
              << std::endl;
    std::cout << std::string(60, '-') << std::endl;

    std::cout << std::setw(12) << "Hyperliquid"
              << std::setw(12) << hl_min
              << std::setw(12) << hl_med
              << std::setw(12) << hl_p99
              << std::setw(12) << std::fixed << std::setprecision(0) << hl_avg
              << std::endl;

    std::cout << std::setw(12) << "dYdX"
              << std::setw(12) << dx_min
              << std::setw(12) << dx_med
              << std::setw(12) << dx_p99
              << std::setw(12) << std::fixed << std::setprecision(0) << dx_avg
              << std::endl;

    std::cout << std::setw(12) << "Injective"
              << std::setw(12) << in_min
              << std::setw(12) << in_med
              << std::setw(12) << in_p99
              << std::setw(12) << std::fixed << std::setprecision(0) << in_avg
              << std::endl;

    std::cout << std::string(60, '-') << std::endl;

    // Check if we hit target
    bool all_pass = (hl_med < 1000 && dx_med < 1000 && in_med < 1000);
    if (all_pass) {
        std::cout << "[PASS] All parsers < 1000ns median" << std::endl;
    } else {
        std::cout << "[WARN] Some parsers > 1000ns median" << std::endl;
    }
}

void test_arbitrage() {
    std::cout << "\n=== ARBITRAGE DETECTION TEST ===" << std::endl;

    // Simulated prices from different DEXes
    double hl_ask = 94125.0;  // Hyperliquid best ask
    double dydx_bid = 94130.0; // dYdX best bid (higher = arb opportunity)

    double spread = (dydx_bid - hl_ask) / hl_ask * 100.0;
    double fees = 0.035 + 0.05;  // HL + dYdX fees
    double net = spread - fees;

    std::cout << "Hyperliquid ASK: $" << std::fixed << std::setprecision(2) << hl_ask << std::endl;
    std::cout << "dYdX BID:        $" << dydx_bid << std::endl;
    std::cout << "Spread:          " << std::setprecision(4) << spread << "%" << std::endl;
    std::cout << "Total Fees:      " << fees << "%" << std::endl;
    std::cout << "Net Profit:      " << net << "%" << std::endl;

    if (net > 0) {
        std::cout << "[PROFITABLE] Buy Hyperliquid, Sell dYdX" << std::endl;
    } else {
        std::cout << "[NO ARB] Spread doesn't cover fees" << std::endl;
    }
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << "  DEX FEED BENCHMARK - Nanosecond Speed" << std::endl;
    std::cout << "========================================" << std::endl;

    test_correctness();
    test_arbitrage();
    benchmark_latency(10000);

    std::cout << "\n========================================" << std::endl;
    std::cout << "  BENCHMARK COMPLETE" << std::endl;
    std::cout << "========================================" << std::endl;

    return 0;
}
