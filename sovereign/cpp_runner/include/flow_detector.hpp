#pragma once
//! DETERMINISTIC FLOW DETECTOR - 100% SIGNALS
//!
//! When exchange spends UTXO, classify WHERE it goes:
//!   INTERNAL (to exchange address) → Consolidating → SHORT_INTERNAL
//!   EXTERNAL (to non-exchange address) → Withdrawal → LONG_EXTERNAL
//!
//! This is NOT prediction. This is observing ACTUAL blockchain behavior.

#include "mmap_addresses.hpp"
#include "utxo_cache.hpp"
#include <string>
#include <vector>
#include <optional>
#include <cstdint>
#include <memory>

// Signal types for deterministic trading
enum class SignalType : uint8_t {
    NONE = 0,
    SHORT_INTERNAL,   // 70%+ outflow to exchange addresses = consolidating = SHORT
    LONG_EXTERNAL,    // 70%+ outflow to non-exchange addresses = withdrawal = LONG
    INFLOW_SHORT,     // Pure inflow (deposit to exchange) = SHORT
    MIXED             // Neither threshold met = skip
};

// Cache-aligned for optimal performance
struct alignas(64) FlowResult {
    std::string txid;
    double inflow_btc;
    double outflow_btc;
    double net_flow;

    // Destination classification (for outflows)
    double internal_btc;      // BTC going to exchange addresses
    double external_btc;      // BTC going to non-exchange addresses
    double internal_pct;      // % going internal
    double external_pct;      // % going external

    SignalType signal;
    std::vector<std::string> source_exchanges;  // Where outflow came from
    std::vector<std::string> dest_exchanges;    // Where internal goes to
    uint64_t latency_ns;
};

class FlowDetector {
public:
    // Thresholds for deterministic signals
    static constexpr double MIN_OUTFLOW_BTC = 1.0;       // Minimum outflow to analyze
    static constexpr double INTERNAL_THRESHOLD = 0.70;   // 70%+ internal = SHORT
    static constexpr double EXTERNAL_THRESHOLD = 0.70;   // 70%+ external = LONG

    FlowDetector(std::shared_ptr<MmapAddressDatabase> addresses, UtxoCache utxo_cache);

    // Process raw transaction bytes from ZMQ with destination classification
    [[nodiscard]] std::optional<FlowResult> process_raw_tx(const uint8_t* data, size_t len);

    // Print statistics
    void print_stats() const;

    [[nodiscard]] uint64_t tx_count() const noexcept { return tx_count_; }
    [[nodiscard]] uint64_t signal_count() const noexcept { return signal_count_; }
    [[nodiscard]] uint64_t short_internal_count() const noexcept { return short_internal_count_; }
    [[nodiscard]] uint64_t long_external_count() const noexcept { return long_external_count_; }

private:
    std::shared_ptr<MmapAddressDatabase> addresses_;
    UtxoCache utxo_cache_;

    // Statistics
    uint64_t tx_count_ = 0;
    uint64_t signal_count_ = 0;
    uint64_t short_internal_count_ = 0;
    uint64_t long_external_count_ = 0;
    uint64_t inflow_short_count_ = 0;
    uint64_t mixed_count_ = 0;
    uint64_t total_latency_ns_ = 0;
};

// Convert signal type to string
inline const char* signal_type_str(SignalType s) {
    switch (s) {
        case SignalType::SHORT_INTERNAL: return "SHORT_INTERNAL";
        case SignalType::LONG_EXTERNAL: return "LONG_EXTERNAL";
        case SignalType::INFLOW_SHORT: return "INFLOW_SHORT";
        case SignalType::MIXED: return "MIXED";
        default: return "NONE";
    }
}
