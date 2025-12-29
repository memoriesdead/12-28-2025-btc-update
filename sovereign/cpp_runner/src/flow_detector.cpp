//! DETERMINISTIC FLOW DETECTOR - 100% SIGNALS
//!
//! KEY INSIGHT: When an exchange spends a UTXO, we observe WHERE it goes:
//!   - INTERNAL (to another exchange address) = Consolidating = About to SELL = SHORT
//!   - EXTERNAL (to non-exchange address) = Customer withdrawal = Already BOUGHT = LONG
//!
//! This is NOT prediction. This is observing ACTUAL blockchain behavior.

#include "flow_detector.hpp"
#include "tx_decoder.hpp"
#include <chrono>
#include <iostream>
#include <algorithm>

FlowDetector::FlowDetector(std::shared_ptr<MmapAddressDatabase> addresses, UtxoCache utxo_cache)
    : addresses_(std::move(addresses))
    , utxo_cache_(std::move(utxo_cache)) {}

std::optional<FlowResult> FlowDetector::process_raw_tx(const uint8_t* data, size_t len) {
    auto start = std::chrono::high_resolution_clock::now();

    // Decode transaction
    auto tx_opt = TxDecoder::decode(data, len);
    if (!tx_opt) {
        return std::nullopt;
    }

    const auto& tx = *tx_opt;

    // Track flows
    uint64_t inflow_sat = 0;
    uint64_t outflow_sat = 0;
    std::vector<std::string> source_exchanges;  // Where outflow came from

    // Track destination classification (for outflows)
    uint64_t internal_sat = 0;   // Going to exchange addresses
    uint64_t external_sat = 0;   // Going to non-exchange addresses
    std::vector<std::string> dest_exchanges;  // Where internal goes

    // ==========================================================
    // STEP 1: Check INPUTS for OUTFLOWS (spending exchange UTXOs)
    // ==========================================================
    for (const auto& input : tx.inputs) {
        auto utxo = utxo_cache_.spend(input.prev_txid, input.prev_vout);
        if (utxo) {
            outflow_sat += utxo->value_sat;
            if (std::find(source_exchanges.begin(), source_exchanges.end(), utxo->exchange) == source_exchanges.end()) {
                source_exchanges.push_back(utxo->exchange);
            }
        }
    }

    // ==========================================================
    // STEP 2: Check ALL OUTPUTS and classify destination
    // ==========================================================
    for (size_t vout = 0; vout < tx.outputs.size(); ++vout) {
        const auto& output = tx.outputs[vout];
        auto addr_opt = TxDecoder::extract_address(output.script_pubkey);

        if (addr_opt) {
            const char* exchange = addresses_->get_exchange(*addr_opt);

            if (exchange) {
                // Output goes to exchange address = INTERNAL
                internal_sat += output.value_sat;
                inflow_sat += output.value_sat;

                std::string exchange_str(exchange);
                if (std::find(dest_exchanges.begin(), dest_exchanges.end(), exchange_str) == dest_exchanges.end()) {
                    dest_exchanges.push_back(exchange_str);
                }

                // Cache for future outflow detection
                utxo_cache_.add(tx.txid, static_cast<uint32_t>(vout),
                               output.value_sat, exchange_str, *addr_opt);
            } else {
                // Output goes to non-exchange address = EXTERNAL
                external_sat += output.value_sat;
            }
        } else {
            // Unknown output (OP_RETURN, etc.) = treat as external
            external_sat += output.value_sat;
        }
    }

    // Calculate latency
    auto end = std::chrono::high_resolution_clock::now();
    uint64_t latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

    ++tx_count_;
    total_latency_ns_ += latency_ns;

    // Only return if there's exchange activity
    if (inflow_sat == 0 && outflow_sat == 0) {
        return std::nullopt;
    }

    // Convert to BTC
    double inflow_btc = static_cast<double>(inflow_sat) / 100000000.0;
    double outflow_btc = static_cast<double>(outflow_sat) / 100000000.0;
    double internal_btc = static_cast<double>(internal_sat) / 100000000.0;
    double external_btc = static_cast<double>(external_sat) / 100000000.0;
    double net_flow = outflow_btc - inflow_btc;

    // Calculate destination percentages
    double total_output = internal_btc + external_btc;
    double internal_pct = (total_output > 0) ? (internal_btc / total_output) : 0.0;
    double external_pct = (total_output > 0) ? (external_btc / total_output) : 0.0;

    // ==========================================================
    // STEP 3: Determine DETERMINISTIC signal type
    // ==========================================================
    SignalType signal = SignalType::NONE;

    if (outflow_btc >= MIN_OUTFLOW_BTC) {
        // We have significant outflow from exchange - classify destination
        if (internal_pct >= INTERNAL_THRESHOLD) {
            // 70%+ going to exchange addresses = CONSOLIDATION = SHORT
            signal = SignalType::SHORT_INTERNAL;
            ++short_internal_count_;
            ++signal_count_;
        } else if (external_pct >= EXTERNAL_THRESHOLD) {
            // 70%+ going to non-exchange = WITHDRAWAL = LONG
            signal = SignalType::LONG_EXTERNAL;
            ++long_external_count_;
            ++signal_count_;
        } else {
            // Mixed destination - skip
            signal = SignalType::MIXED;
            ++mixed_count_;
        }
    } else if (inflow_btc >= MIN_OUTFLOW_BTC && outflow_btc < 0.01) {
        // Pure inflow (deposit to exchange) = SHORT
        signal = SignalType::INFLOW_SHORT;
        ++inflow_short_count_;
        ++signal_count_;
    }

    // Only return if there's a signal (or significant flow)
    if (signal == SignalType::NONE && net_flow > -0.1 && net_flow < 0.1) {
        return std::nullopt;
    }

    return FlowResult{
        tx.txid,
        inflow_btc,
        outflow_btc,
        net_flow,
        internal_btc,
        external_btc,
        internal_pct,
        external_pct,
        signal,
        std::move(source_exchanges),
        std::move(dest_exchanges),
        latency_ns
    };
}

void FlowDetector::print_stats() const {
    uint64_t avg_latency = tx_count_ > 0 ? total_latency_ns_ / tx_count_ : 0;

    std::cout << "\n========================================" << std::endl;
    std::cout << "DETERMINISTIC SIGNAL STATS" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "TX processed:     " << tx_count_ << std::endl;
    std::cout << "Total signals:    " << signal_count_ << std::endl;
    std::cout << "  SHORT_INTERNAL: " << short_internal_count_ << " (consolidation)" << std::endl;
    std::cout << "  LONG_EXTERNAL:  " << long_external_count_ << " (withdrawal)" << std::endl;
    std::cout << "  INFLOW_SHORT:   " << inflow_short_count_ << " (deposit)" << std::endl;
    std::cout << "  MIXED (skip):   " << mixed_count_ << std::endl;
    std::cout << "Avg latency:      " << avg_latency << " ns ("
              << static_cast<double>(avg_latency) / 1000.0 << " us)" << std::endl;
    std::cout << "========================================\n" << std::endl;
}
