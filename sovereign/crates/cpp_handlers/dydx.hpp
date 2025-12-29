/**
 * dYdX v4 DEX Handler - Nanosecond Latency
 *
 * Indexer WebSocket: wss://indexer.dydx.trade/v4/ws
 * Indexer REST: https://indexer.dydx.trade/v4
 * Local Node RPC: http://localhost:26657 (when running dydxprotocold)
 *
 * Fees: 0.02% maker, 0.05% taker
 *
 * WebSocket subscribe message:
 * {"type": "subscribe", "channel": "v4_orderbook", "id": "BTC-USD"}
 *
 * WebSocket response format:
 * {
 *   "type": "subscribed",
 *   "channel": "v4_orderbook",
 *   "id": "BTC-USD",
 *   "contents": {
 *     "bids": [{"price": "94000", "size": "1.5"}],
 *     "asks": [{"price": "94001", "size": "2.0"}]
 *   }
 * }
 *
 * REST endpoint: /v4/orderbooks/perpetualMarket/BTC-USD
 */

#pragma once

#include "../order_book_types.hpp"
#include <string>
#include <cstdlib>
#include <chrono>
#include <tuple>

namespace sovereign {
namespace exchange {

class DydxHandler {
public:
    // Public Indexer API
    static constexpr const char* WS_URL = "wss://indexer.dydx.trade/v4/ws";
    static constexpr const char* REST_URL = "https://indexer.dydx.trade/v4/orderbooks/perpetualMarket/BTC-USD";

    // Local node RPC (nanosecond latency when synced)
    static constexpr const char* LOCAL_RPC_URL = "http://localhost:26657";

    static constexpr const char* SYMBOL = "BTC-USD";
    static constexpr double MAKER_FEE_PCT = 0.02;  // 0.02%
    static constexpr double TAKER_FEE_PCT = 0.05;  // 0.05%

    /**
     * Get WebSocket subscription message.
     */
    static std::string get_subscribe_message(const std::string& market = "BTC-USD") {
        return "{\"type\": \"subscribe\", \"channel\": \"v4_orderbook\", \"id\": \"" + market + "\"}";
    }

    /**
     * Get trades subscription message.
     */
    static std::string get_trades_subscribe_message(const std::string& market = "BTC-USD") {
        return "{\"type\": \"subscribe\", \"channel\": \"v4_trades\", \"id\": \"" + market + "\"}";
    }

    /**
     * Get heartbeat/ping message.
     */
    static std::string get_heartbeat_message() {
        return "{\"type\": \"ping\"}";
    }

    /**
     * Parse REST orderbook response into OrderBook.
     * Response: {"bids": [{"price": "94000", "size": "1.5"}], "asks": [...]}
     */
    static bool parse_rest_response(const std::string& json, OrderBook& book) {
        auto start = std::chrono::high_resolution_clock::now();

        book.bids.clear();
        book.asks.clear();
        book.exchange = Exchange::DYDX;

        // Parse bids
        size_t bids_pos = json.find("\"bids\"");
        if (bids_pos != std::string::npos) {
            size_t arr_start = json.find('[', bids_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_dydx_levels(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
            }
        }

        // Parse asks
        size_t asks_pos = json.find("\"asks\"");
        if (asks_pos != std::string::npos) {
            size_t arr_start = json.find('[', asks_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_dydx_levels(json.substr(arr_start, arr_end - arr_start + 1), book.asks);
            }
        }

        auto end = std::chrono::high_resolution_clock::now();
        book.parse_latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

        return book.is_valid();
    }

    /**
     * Parse WebSocket message into OrderBook.
     */
    static bool parse_ws_message(const std::string& json, OrderBook& book) {
        // Check if this is an orderbook message
        if (json.find("\"channel\":\"v4_orderbook\"") == std::string::npos &&
            json.find("\"channel\": \"v4_orderbook\"") == std::string::npos) {
            return false;
        }

        // Find contents object
        size_t contents_pos = json.find("\"contents\"");
        if (contents_pos == std::string::npos) {
            // Might be direct format without contents wrapper
            return parse_rest_response(json, book);
        }

        return parse_rest_response(json.substr(contents_pos), book);
    }

    /**
     * Parse trades WebSocket message to calculate flow.
     * Returns: {buy_volume, sell_volume, imbalance_pct}
     */
    static std::tuple<double, double, double> parse_trades(const std::string& json) {
        double buy_vol = 0.0, sell_vol = 0.0;

        size_t pos = 0;
        while (pos < json.size()) {
            // Find next trade
            size_t side_pos = json.find("\"side\"", pos);
            if (side_pos == std::string::npos) break;

            // Get side value
            size_t side_val_start = json.find(':', side_pos) + 1;
            while (side_val_start < json.size() && (json[side_val_start] == ' ' || json[side_val_start] == '"')) side_val_start++;

            bool is_buy = (json[side_val_start] == 'B' || json[side_val_start] == 'b');

            // Find price and size
            size_t price_pos = json.find("\"price\"", side_pos);
            size_t size_pos = json.find("\"size\"", side_pos);

            if (price_pos != std::string::npos && size_pos != std::string::npos) {
                double price = parse_string_number(json, price_pos);
                double size = parse_string_number(json, size_pos);
                double notional = price * size;

                if (is_buy) {
                    buy_vol += notional;
                } else {
                    sell_vol += notional;
                }
            }

            pos = side_pos + 10;
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

    // Parse dYdX level format: [{"price": "94000", "size": "1.5"}, ...]
    static void parse_dydx_levels(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t pos = 0;
        while (pos < arr.size() && levels.size() < MAX_BOOK_LEVELS) {
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
