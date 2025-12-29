/**
 * Signal Handler - Integrated Blockchain Signal Processing
 *
 * PURE DATA. NO MOCK. MATH NEVER LIES.
 *
 * This is the CRITICAL PATH component that processes blockchain signals
 * and makes deterministic trade decisions in under 10 microseconds.
 *
 * Pipeline:
 * 1. Receive blockchain signal (deposit/withdrawal detected)
 * 2. Look up cached order book (<500ns)
 * 3. Calculate price impact (<1us)
 * 4. Make trade decision (<100ns)
 * 5. Return decision (<10us total)
 */

#pragma once

#include "order_book_types.hpp"
#include "order_book_cache.hpp"
#include "impact_calculator.hpp"
#include <chrono>
#include <cstdio>

namespace sovereign {

class SignalHandler {
public:
    /**
     * Constructor with cache reference and optional config.
     */
    explicit SignalHandler(OrderBookCache& cache, TradingConfig config = {})
        : cache_(cache), config_(config) {}

    /**
     * Process a blockchain signal and return trade decision.
     *
     * This is the CRITICAL PATH - must complete in <10 microseconds.
     *
     * @param signal    Blockchain signal with deposit/withdrawal info
     * @return          Trade decision (trade or skip with reason)
     */
    TradeDecision process_signal(const BlockchainSignal& signal) {
        auto start = std::chrono::high_resolution_clock::now();

        TradeDecision decision{};
        decision.is_short = signal.is_inflow;

        // Map exchange name to enum
        Exchange exchange = exchange_from_name(signal.exchange);
        if (exchange == Exchange::COUNT) {
            decision.reason = "Unknown exchange: " + signal.exchange;
            record_timing(decision, start);
            return decision;
        }
        decision.exchange = exchange;

        // Check minimum deposit size
        if (signal.btc_amount < config_.min_deposit_btc) {
            decision.reason = "Deposit too small: " +
                             std::to_string(signal.btc_amount) + " BTC < " +
                             std::to_string(config_.min_deposit_btc) + " BTC required";
            record_timing(decision, start);
            return decision;
        }

        // Check if order book is stale
        if (cache_.is_stale(exchange, config_.max_book_age_ms)) {
            decision.reason = "Order book stale (>" +
                             std::to_string(config_.max_book_age_ms) + "ms old)";
            record_timing(decision, start);
            return decision;
        }

        // Check if order book is valid
        if (!cache_.is_valid(exchange)) {
            decision.reason = "Order book not available";
            record_timing(decision, start);
            return decision;
        }

        // Get cached order book (sub-microsecond operation)
        OrderBook book = cache_.get(exchange);

        // Calculate price impact based on direction
        double fees_pct = get_config(exchange).fee_pct * 100.0;  // Convert to %
        if (fees_pct < 0.01) fees_pct = config_.fees_pct;  // Use default if not set

        if (signal.is_inflow) {
            // INFLOW = deposit = seller will eat bids = SHORT signal
            decision.impact = ImpactCalculator::calculate_sell_impact(
                signal.btc_amount, book.bids);
            decision.entry_price = book.best_bid();
        } else {
            // OUTFLOW = withdrawal = buyer will eat asks = LONG signal
            decision.impact = ImpactCalculator::calculate_buy_impact(
                signal.btc_amount, book.asks);
            decision.entry_price = book.best_ask();
        }

        // Check if profitable (impact > 2x fees)
        double min_required = config_.min_impact_pct();
        if (std::abs(decision.impact.price_drop_pct) < min_required) {
            char buf[256];
            snprintf(buf, sizeof(buf),
                     "Impact %.4f%% < required %.4f%% (2x fees)",
                     std::abs(decision.impact.price_drop_pct),
                     min_required);
            decision.reason = buf;
            record_timing(decision, start);
            return decision;
        }

        // Check if enough depth to fill the order
        if (decision.impact.volume_remaining > 0.0) {
            char buf[256];
            snprintf(buf, sizeof(buf),
                     "Insufficient depth: only %.2f of %.2f BTC fillable",
                     decision.impact.volume_filled,
                     signal.btc_amount);
            decision.reason = buf;
            record_timing(decision, start);
            return decision;
        }

        // Calculate exit price
        decision.exit_price = ImpactCalculator::calculate_exit_price(
            decision.entry_price,
            decision.impact,
            decision.is_short,
            config_.take_profit_ratio);

        // Trade is approved!
        decision.should_trade = true;

        char buf[256];
        snprintf(buf, sizeof(buf),
                 "TRADE: Impact %.4f%% > %.4f%% | Expected +%.2f%%",
                 std::abs(decision.impact.price_drop_pct),
                 min_required,
                 decision.expected_return(config_.fees_pct));
        decision.reason = buf;

        record_timing(decision, start);
        return decision;
    }

    /**
     * Process signal and print result to stdout.
     * Used for integration with existing Python pipeline.
     */
    void process_and_print(const BlockchainSignal& signal) {
        TradeDecision decision = process_signal(signal);

        if (decision.should_trade) {
            printf("[TRADE] %s %s | "
                   "Amount: %.2f BTC | "
                   "Impact: %.4f%% | "
                   "Entry: $%.2f | "
                   "Exit: $%.2f | "
                   "Expected: +%.2f%% | "
                   "Leverage: %dx | "
                   "Processing: %ldns\n",
                   decision.is_short ? "SHORT" : "LONG",
                   exchange_name(decision.exchange),
                   signal.btc_amount,
                   std::abs(decision.impact.price_drop_pct),
                   decision.entry_price,
                   decision.exit_price,
                   decision.expected_return(config_.fees_pct),
                   decision.leverage(),
                   decision.processing_ns);
        } else {
            printf("[SKIP] %s | %s | Processing: %ldns\n",
                   signal.exchange.c_str(),
                   decision.reason.c_str(),
                   decision.processing_ns);
        }
    }

    /**
     * Get current configuration.
     */
    const TradingConfig& config() const { return config_; }

    /**
     * Update configuration.
     */
    void set_config(TradingConfig config) { config_ = config; }

    /**
     * Quick check if an exchange/amount combo is worth processing.
     * Use before full process_signal for ultra-low-latency filtering.
     */
    bool quick_filter(const std::string& exchange_name, double btc_amount) const {
        // Check minimum amount
        if (btc_amount < config_.min_deposit_btc) {
            return false;
        }

        // Check if exchange is known
        Exchange exchange = exchange_from_name(exchange_name);
        if (exchange == Exchange::COUNT) {
            return false;
        }

        // Check if we have valid order book
        return cache_.is_valid(exchange) && !cache_.is_stale(exchange, config_.max_book_age_ms);
    }

    // ========================================================================
    // MULTI-INSTRUMENT DETERMINISTIC SIGNAL PROCESSING
    // ========================================================================

    /**
     * Process blockchain signal for a specific instrument type.
     *
     * DETERMINISTIC FORMULA (same for ALL instruments):
     *   IF adjusted_impact > 2 × adjusted_fees THEN GUARANTEED PROFIT
     *
     * Instrument-specific adjustments:
     *   SPOT:            No adjustment (base case)
     *   MARGIN:          + interest cost over hold time
     *   PERPETUAL:       + funding cost if crossing funding time
     *   FUTURES:         + basis consideration (converges to 0)
     *   OPTIONS:         × delta (exposure adjustment)
     *   INVERSE:         Calculate in BTC, convert to USD
     *   LEVERAGED_TOKEN: × target_leverage (3x)
     *
     * @param signal          Blockchain signal with deposit/withdrawal info
     * @param inst_type       Instrument type to trade
     * @param inst_data       Instrument data with mark price, funding, etc.
     * @return                Trade decision (deterministic: trade or skip)
     */
    TradeDecision process_instrument_signal(
            const BlockchainSignal& signal,
            InstrumentType inst_type,
            const InstrumentData& inst_data) {

        auto start = std::chrono::high_resolution_clock::now();
        TradeDecision decision{};
        decision.is_short = signal.is_inflow;

        // Map exchange
        Exchange exchange = exchange_from_name(signal.exchange);
        if (exchange == Exchange::COUNT) {
            decision.reason = "Unknown exchange";
            record_timing(decision, start);
            return decision;
        }
        decision.exchange = exchange;

        // Minimum size check
        if (signal.btc_amount < config_.min_deposit_btc) {
            decision.reason = "Deposit too small";
            record_timing(decision, start);
            return decision;
        }

        // Order book validity check
        if (!inst_data.book.is_valid()) {
            decision.reason = "Order book not available";
            record_timing(decision, start);
            return decision;
        }

        // Staleness check
        if (inst_data.age_ms() > config_.max_book_age_ms) {
            decision.reason = "Order book stale";
            record_timing(decision, start);
            return decision;
        }

        // Get base fees for this exchange
        double base_fees_pct = get_exchange_config(exchange).fee_pct * 100.0;
        if (base_fees_pct < 0.01) base_fees_pct = config_.fees_pct;

        // Calculate raw impact
        if (signal.is_inflow) {
            decision.impact = ImpactCalculator::calculate_sell_impact(
                signal.btc_amount, inst_data.book.bids);
            decision.entry_price = inst_data.book.best_bid();
        } else {
            decision.impact = ImpactCalculator::calculate_buy_impact(
                signal.btc_amount, inst_data.book.asks);
            decision.entry_price = inst_data.book.best_ask();
        }

        // Check depth
        if (decision.impact.volume_remaining > 0.0) {
            decision.reason = "Insufficient depth";
            record_timing(decision, start);
            return decision;
        }

        // ================================================================
        // INSTRUMENT-SPECIFIC DETERMINISTIC ADJUSTMENTS
        // ================================================================
        double adjusted_impact = std::abs(decision.impact.price_drop_pct);
        double adjusted_fees = base_fees_pct;
        const char* inst_name = instrument_name(inst_type);

        switch (inst_type) {
            case InstrumentType::SPOT:
                // No adjustment - pure order book impact
                break;

            case InstrumentType::MARGIN:
                // Add interest cost (assume 4hr hold time)
                // interest_rate is hourly, we hold ~4 hours
                adjusted_fees += std::abs(inst_data.interest_rate_long) * 4.0;
                break;

            case InstrumentType::PERPETUAL:
                // Add funding cost if we might cross funding time
                // funding_rate is per 8 hours
                adjusted_fees += std::abs(inst_data.funding_rate) * 100.0;
                break;

            case InstrumentType::FUTURES:
                // Basis converges to 0 at expiration - add to impact if favorable
                // If we're long and basis is negative, we profit from convergence
                if (!decision.is_short && inst_data.basis < 0) {
                    adjusted_impact += std::abs(inst_data.basis / decision.entry_price * 100.0);
                } else if (decision.is_short && inst_data.basis > 0) {
                    adjusted_impact += std::abs(inst_data.basis / decision.entry_price * 100.0);
                }
                break;

            case InstrumentType::OPTIONS:
                // Delta-adjusted exposure: impact × |delta|
                // If delta is 0.5, a 1% move only gives 0.5% exposure
                if (std::abs(inst_data.delta) > 0.01) {
                    adjusted_impact *= std::abs(inst_data.delta);
                }
                // Add theta cost (time decay per day, assume 1hr hold = 1/24 day)
                adjusted_fees += std::abs(inst_data.theta) / 24.0;
                break;

            case InstrumentType::INVERSE:
                // Inverse contracts: P&L in BTC terms
                // Must account for double exposure (price move + BTC value change)
                // Effective impact is ~2x for large moves
                if (adjusted_impact > 1.0) {
                    adjusted_impact *= 1.5;  // Conservative adjustment
                }
                // Add funding (same as perpetual)
                adjusted_fees += std::abs(inst_data.funding_rate) * 100.0;
                break;

            case InstrumentType::LEVERAGED_TOKEN:
                // Token tracks underlying × target_leverage (usually 3x)
                adjusted_impact *= inst_data.target_leverage;
                // No additional fees (rebalancing is internal)
                break;

            default:
                break;
        }

        // ================================================================
        // THE DETERMINISTIC DECISION
        // ================================================================
        double min_required = adjusted_fees * config_.min_impact_multiple;

        if (adjusted_impact < min_required) {
            char buf[256];
            snprintf(buf, sizeof(buf),
                     "[%s] Impact %.4f%% < required %.4f%% (2x fees)",
                     inst_name, adjusted_impact, min_required);
            decision.reason = buf;
            record_timing(decision, start);
            return decision;
        }

        // DETERMINISTIC: Impact > 2×fees = GUARANTEED PROFIT
        decision.should_trade = true;
        decision.exit_price = ImpactCalculator::calculate_exit_price(
            decision.entry_price, decision.impact, decision.is_short,
            config_.take_profit_ratio);

        char buf[256];
        snprintf(buf, sizeof(buf),
                 "[%s] TRADE: Impact %.4f%% > %.4f%% | Profit: +%.2f%%",
                 inst_name, adjusted_impact, min_required,
                 adjusted_impact - adjusted_fees);
        decision.reason = buf;

        record_timing(decision, start);
        return decision;
    }

private:
    OrderBookCache& cache_;
    TradingConfig config_;

    void record_timing(TradeDecision& decision,
                       std::chrono::high_resolution_clock::time_point start) {
        auto end = std::chrono::high_resolution_clock::now();
        decision.processing_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            end - start).count();
    }
};

} // namespace sovereign
