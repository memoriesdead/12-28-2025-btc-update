/**
 * Impact Calculator - Deterministic Price Impact Mathematics
 *
 * PURE DATA. NO MOCK. MATH NEVER LIES.
 *
 * This implements the core mathematical formulas for calculating exact
 * price impact when a given volume trades through the order book.
 *
 * Port of Python depth_calculator.py to C++ for sub-microsecond execution.
 *
 * Key formulas:
 * 1. Price Impact = (start_price - end_price) / start_price * 100
 * 2. VWAP = sum(price_i * volume_i) / sum(volume_i)
 * 3. Profit = Impact% - Fees%
 * 4. Leveraged Return = Profit * Leverage
 */

#pragma once

#include "order_book_types.hpp"
#include <cmath>
#include <algorithm>

namespace sovereign {

class ImpactCalculator {
public:
    // ========================================================================
    // SELL IMPACT (eating into bids - price drops)
    // ========================================================================

    /**
     * Calculate price impact for a SELL order eating through bids.
     *
     * When someone deposits BTC to an exchange and sells, they eat through
     * the bid side of the book, causing price to drop.
     *
     * @param sell_btc  Amount of BTC being sold
     * @param bids      Order book bids, sorted by price DESCENDING
     * @return          PriceImpact structure with all calculated values
     *
     * Performance: <1 microsecond for 50 levels
     */
    static PriceImpact calculate_sell_impact(
            double sell_btc,
            const std::vector<PriceLevel>& bids) {

        PriceImpact impact{};

        if (bids.empty() || sell_btc <= 0.0) {
            impact.volume_remaining = sell_btc;
            return impact;
        }

        double remaining = sell_btc;
        impact.start_price = bids[0].price;
        impact.end_price = impact.start_price;

        for (const auto& level : bids) {
            if (remaining <= 0.0) break;

            double fill = std::min(remaining, level.volume);
            impact.total_cost += level.price * fill;
            impact.volume_filled += fill;
            remaining -= fill;
            impact.end_price = level.price;
            ++impact.levels_eaten;
        }

        impact.volume_remaining = remaining;

        // Calculate VWAP (Volume-Weighted Average Price)
        if (impact.volume_filled > 0.0) {
            impact.vwap = impact.total_cost / impact.volume_filled;
        } else {
            impact.vwap = impact.start_price;
        }

        // Calculate percentage drop
        if (impact.start_price > 0.0) {
            impact.price_drop_pct = (impact.start_price - impact.end_price)
                                    / impact.start_price * 100.0;
        }

        return impact;
    }

    // ========================================================================
    // BUY IMPACT (eating into asks - price rises)
    // ========================================================================

    /**
     * Calculate price impact for a BUY order eating through asks.
     *
     * When someone withdraws BTC and buys, they eat through the ask side,
     * causing price to rise.
     *
     * @param buy_btc   Amount of BTC being bought
     * @param asks      Order book asks, sorted by price ASCENDING
     * @return          PriceImpact structure (price_drop_pct will be negative)
     */
    static PriceImpact calculate_buy_impact(
            double buy_btc,
            const std::vector<PriceLevel>& asks) {

        PriceImpact impact{};

        if (asks.empty() || buy_btc <= 0.0) {
            impact.volume_remaining = buy_btc;
            return impact;
        }

        double remaining = buy_btc;
        impact.start_price = asks[0].price;
        impact.end_price = impact.start_price;

        for (const auto& level : asks) {
            if (remaining <= 0.0) break;

            double fill = std::min(remaining, level.volume);
            impact.total_cost += level.price * fill;
            impact.volume_filled += fill;
            remaining -= fill;
            impact.end_price = level.price;
            ++impact.levels_eaten;
        }

        impact.volume_remaining = remaining;

        // Calculate VWAP
        if (impact.volume_filled > 0.0) {
            impact.vwap = impact.total_cost / impact.volume_filled;
        } else {
            impact.vwap = impact.start_price;
        }

        // For buys, price rises (store as negative drop for consistency)
        if (impact.start_price > 0.0) {
            impact.price_drop_pct = -((impact.end_price - impact.start_price)
                                      / impact.start_price * 100.0);
        }

        return impact;
    }

    // ========================================================================
    // EXIT PRICE CALCULATION
    // ========================================================================

    /**
     * Calculate the target exit price based on expected impact.
     *
     * We exit at a fraction (default 80%) of the expected price move
     * to ensure we capture most of the profit with a safety margin.
     *
     * @param entry_price       Price at entry
     * @param impact            Calculated price impact
     * @param is_short          true for SHORT, false for LONG
     * @param take_profit_ratio Fraction of impact to capture (default 0.8)
     * @return                  Target exit price
     */
    static double calculate_exit_price(
            double entry_price,
            const PriceImpact& impact,
            bool is_short,
            double take_profit_ratio = 0.8) {

        if (is_short) {
            // SHORT: Price will drop, exit below entry
            // Target = entry * (1 - target_drop%)
            double target_drop_pct = std::abs(impact.price_drop_pct) * take_profit_ratio;
            return entry_price * (1.0 - target_drop_pct / 100.0);
        } else {
            // LONG: Price will rise, exit above entry
            // Target = entry * (1 + target_rise%)
            double target_rise_pct = std::abs(impact.price_drop_pct) * take_profit_ratio;
            return entry_price * (1.0 + target_rise_pct / 100.0);
        }
    }

    // ========================================================================
    // CUMULATIVE DEPTH ANALYSIS
    // ========================================================================

    /**
     * Calculate cumulative depth at each price level.
     *
     * Returns a vector showing:
     * - How much volume is available up to each level
     * - What % drop occurs at each level
     *
     * Useful for finding the optimal trade size.
     */
    struct DepthLevel {
        double price;
        double volume;
        double cumulative_volume;
        double pct_drop;
    };

    static std::vector<DepthLevel> calculate_cumulative_depth(
            const std::vector<PriceLevel>& levels,
            size_t max_levels = 50) {

        std::vector<DepthLevel> result;
        result.reserve(std::min(max_levels, levels.size()));

        if (levels.empty()) return result;

        double start_price = levels[0].price;
        double cumulative = 0.0;

        size_t count = std::min(max_levels, levels.size());
        for (size_t i = 0; i < count; ++i) {
            const auto& level = levels[i];
            cumulative += level.volume;

            double pct_drop = 0.0;
            if (start_price > 0.0) {
                pct_drop = std::abs(start_price - level.price) / start_price * 100.0;
            }

            result.push_back({
                level.price,
                level.volume,
                cumulative,
                pct_drop
            });
        }

        return result;
    }

    // ========================================================================
    // UTILITY FUNCTIONS
    // ========================================================================

    /**
     * Calculate total depth on one side of the book.
     */
    static double total_depth(
            const std::vector<PriceLevel>& levels,
            size_t max_levels = 50) {

        double total = 0.0;
        size_t count = std::min(max_levels, levels.size());
        for (size_t i = 0; i < count; ++i) {
            total += levels[i].volume;
        }
        return total;
    }

    /**
     * Find minimum BTC needed to cause a given % impact.
     */
    static double min_btc_for_impact(
            const std::vector<PriceLevel>& bids,
            double target_impact_pct) {

        if (bids.empty() || target_impact_pct <= 0.0) {
            return 0.0;
        }

        double start_price = bids[0].price;
        double target_price = start_price * (1.0 - target_impact_pct / 100.0);
        double volume_needed = 0.0;

        for (const auto& level : bids) {
            if (level.price <= target_price) {
                break;
            }
            volume_needed += level.volume;
        }

        return volume_needed;
    }

    /**
     * Calculate VWAP for a given volume.
     */
    static double calculate_vwap(
            const std::vector<PriceLevel>& levels,
            double volume) {

        if (levels.empty() || volume <= 0.0) {
            return levels.empty() ? 0.0 : levels[0].price;
        }

        double remaining = volume;
        double total_cost = 0.0;
        double total_volume = 0.0;

        for (const auto& level : levels) {
            if (remaining <= 0.0) break;

            double fill = std::min(remaining, level.volume);
            total_cost += level.price * fill;
            total_volume += fill;
            remaining -= fill;
        }

        return (total_volume > 0.0) ? (total_cost / total_volume) : levels[0].price;
    }

    /**
     * Check if a trade would be profitable.
     *
     * A trade is profitable if:
     * impact_pct > fees_pct * safety_multiple
     *
     * With safety_multiple = 2.0 (default), we need impact > 2x fees.
     */
    static bool is_profitable(
            double impact_pct,
            double fees_pct,
            double safety_multiple = 2.0) {

        return std::abs(impact_pct) >= (fees_pct * safety_multiple);
    }

    /**
     * Calculate expected profit percentage.
     */
    static double expected_profit_pct(
            double impact_pct,
            double fees_pct) {

        return std::abs(impact_pct) - fees_pct;
    }

    /**
     * Calculate leveraged return.
     */
    static double leveraged_return(
            double impact_pct,
            double fees_pct,
            int leverage) {

        double net_profit = expected_profit_pct(impact_pct, fees_pct);
        return (net_profit > 0.0) ? (net_profit * leverage) : 0.0;
    }

    // ========================================================================
    // FULL ANALYSIS
    // ========================================================================

    /**
     * Perform complete analysis for a potential trade.
     *
     * Given a signal (deposit/withdrawal) and order book, calculate:
     * - Price impact
     * - Expected profit
     * - Leveraged return
     * - Whether trade is profitable
     */
    struct TradeAnalysis {
        PriceImpact impact;
        double expected_profit_pct;
        double leveraged_return;
        bool is_profitable;
        double entry_price;
        double exit_price;
        int leverage;
    };

    static TradeAnalysis analyze_trade(
            double btc_amount,
            bool is_sell,  // true = sell (SHORT), false = buy (LONG)
            const std::vector<PriceLevel>& bids,
            const std::vector<PriceLevel>& asks,
            double fees_pct = 0.10,
            int leverage = 100,
            double take_profit_ratio = 0.8,
            double safety_multiple = 2.0) {

        TradeAnalysis analysis{};
        analysis.leverage = leverage;

        if (is_sell) {
            // Selling into bids
            analysis.impact = calculate_sell_impact(btc_amount, bids);
            analysis.entry_price = bids.empty() ? 0.0 : bids[0].price;
        } else {
            // Buying into asks
            analysis.impact = calculate_buy_impact(btc_amount, asks);
            analysis.entry_price = asks.empty() ? 0.0 : asks[0].price;
        }

        analysis.expected_profit_pct = expected_profit_pct(
            analysis.impact.price_drop_pct, fees_pct);

        analysis.leveraged_return = leveraged_return(
            analysis.impact.price_drop_pct, fees_pct, leverage);

        analysis.is_profitable = is_profitable(
            analysis.impact.price_drop_pct, fees_pct, safety_multiple);

        if (analysis.is_profitable) {
            analysis.exit_price = calculate_exit_price(
                analysis.entry_price,
                analysis.impact,
                is_sell,
                take_profit_ratio);
        }

        return analysis;
    }
};

} // namespace sovereign
