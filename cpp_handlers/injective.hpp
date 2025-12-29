/**
 * Injective DEX Handler - Nanosecond Latency
 *
 * Exchange API: https://sentry.lcd.injective.network/api/exchange
 * Chain gRPC: localhost:9090 (when running injectived)
 * Indexer: https://k8s.global.mainnet.chain.grpc.injective.network
 *
 * Fees: 0.10% taker
 *
 * Orderbook endpoint: /v1/spot/orderbook/{market_id}
 * Trades endpoint: /v1/spot/trades
 *
 * Response format:
 * {
 *   "orderbook": {
 *     "buys": [{"price": "94000", "quantity": "1.5"}],
 *     "sells": [{"price": "94001", "quantity": "2.0"}]
 *   }
 * }
 */

#pragma once

#include "../order_book_types.hpp"
#include <string>
#include <cstdlib>
#include <chrono>
#include <tuple>

namespace sovereign {
namespace exchange {

class InjectiveHandler {
public:
    // Public Indexer API
    static constexpr const char* REST_URL = "https://sentry.lcd.injective.network/api/exchange/v1";

    // Local node gRPC (nanosecond latency when synced)
    static constexpr const char* LOCAL_GRPC_URL = "localhost:9090";

    // BTC/USDT perpetual market ID on Injective
    static constexpr const char* BTC_MARKET_ID = "0x4ca0f92fc28be0c9761f1ac5c0a15e4c5b4c3c68e8b6f38e8c0e11f6d1a63f6e";

    static constexpr const char* SYMBOL = "BTC/USDT";
    static constexpr double TAKER_FEE_PCT = 0.10;  // 0.10%

    /**
     * Get REST endpoint for orderbook.
     */
    static std::string get_orderbook_url(const std::string& market_id = BTC_MARKET_ID) {
        return std::string(REST_URL) + "/spot/orderbook/" + market_id;
    }

    /**
     * Get REST endpoint for trades.
     */
    static std::string get_trades_url(const std::string& market_id = BTC_MARKET_ID) {
        return std::string(REST_URL) + "/spot/trades?market_id=" + market_id;
    }

    /**
     * Parse REST orderbook response into OrderBook.
     * Response: {"orderbook": {"buys": [...], "sells": [...]}}
     */
    static bool parse_rest_response(const std::string& json, OrderBook& book) {
        auto start = std::chrono::high_resolution_clock::now();

        book.bids.clear();
        book.asks.clear();
        book.exchange = Exchange::INJECTIVE;

        // Parse buys (bids)
        size_t buys_pos = json.find("\"buys\"");
        if (buys_pos != std::string::npos) {
            size_t arr_start = json.find('[', buys_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_inj_levels(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
            }
        }

        // Parse sells (asks)
        size_t sells_pos = json.find("\"sells\"");
        if (sells_pos != std::string::npos) {
            size_t arr_start = json.find('[', sells_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_inj_levels(json.substr(arr_start, arr_end - arr_start + 1), book.asks);
            }
        }

        auto end = std::chrono::high_resolution_clock::now();
        book.parse_latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

        return book.is_valid();
    }

    /**
     * Parse trades response to calculate flow.
     * Returns: {buy_volume, sell_volume, imbalance_pct}
     */
    static std::tuple<double, double, double> parse_trades(const std::string& json) {
        double buy_vol = 0.0, sell_vol = 0.0;

        size_t pos = 0;
        while (pos < json.size()) {
            // Find trade direction
            size_t dir_pos = json.find("\"trade_direction\"", pos);
            if (dir_pos == std::string::npos) {
                // Try alternate field name
                dir_pos = json.find("\"direction\"", pos);
                if (dir_pos == std::string::npos) break;
            }

            // Get direction value
            size_t val_start = json.find(':', dir_pos) + 1;
            while (val_start < json.size() && (json[val_start] == ' ' || json[val_start] == '"')) val_start++;

            // "buy" or "sell"
            bool is_buy = (json[val_start] == 'b' || json[val_start] == 'B');

            // Find price and quantity
            size_t price_pos = json.find("\"price\"", dir_pos);
            size_t qty_pos = json.find("\"quantity\"", dir_pos);

            if (price_pos != std::string::npos && qty_pos != std::string::npos) {
                double price = parse_string_number(json, price_pos);
                double qty = parse_string_number(json, qty_pos);
                double notional = price * qty;

                if (is_buy) {
                    buy_vol += notional;
                } else {
                    sell_vol += notional;
                }
            }

            pos = dir_pos + 15;
        }

        double total = buy_vol + sell_vol;
        double imbalance = total > 0 ? (buy_vol - sell_vol) / total * 100.0 : 0.0;

        return {buy_vol, sell_vol, imbalance};
    }

private:
    static size_t find_matching_bracket(const std::string& s, size_t start) {
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

    // Parse Injective level format: [{"price": "94000", "quantity": "1.5"}, ...]
    static void parse_inj_levels(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t pos = 0;
        while (pos < arr.size() && levels.size() < MAX_BOOK_LEVELS) {
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

    static double parse_string_number(const std::string& s, size_t key_pos) {
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
};

} // namespace exchange
} // namespace sovereign
