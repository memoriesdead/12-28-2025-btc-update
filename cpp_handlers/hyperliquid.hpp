/**
 * Hyperliquid DEX Handler - Nanosecond Latency
 *
 * REST API: POST https://api.hyperliquid.xyz/info
 * WebSocket: wss://api.hyperliquid.xyz/ws
 * Local Node: http://localhost:3001/info (when running hl-visor)
 *
 * Fees: 0.035% taker
 *
 * REST request bodies:
 *   Orderbook: {"type": "l2Book", "coin": "BTC"}
 *   Trades: {"type": "recentTrades", "coin": "BTC"}
 *   Meta: {"type": "metaAndAssetCtxs"}
 *
 * REST response format (l2Book):
 * {
 *   "levels": [
 *     [{"px": "94000.0", "sz": "1.5", "n": 5}],  // bids
 *     [{"px": "94001.0", "sz": "2.0", "n": 3}]   // asks
 *   ]
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

class HyperliquidHandler {
public:
    // Public API (use when node not available)
    static constexpr const char* WS_URL = "wss://api.hyperliquid.xyz/ws";
    static constexpr const char* REST_URL = "https://api.hyperliquid.xyz/info";

    // Local node (nanosecond latency when running)
    static constexpr const char* LOCAL_REST_URL = "http://localhost:3001/info";

    static constexpr const char* SYMBOL = "BTC";
    static constexpr double FEE_PCT = 0.035;  // 0.035%

    /**
     * Get REST request body for orderbook.
     */
    static std::string get_orderbook_request(const std::string& coin = "BTC") {
        return "{\"type\": \"l2Book\", \"coin\": \"" + coin + "\"}";
    }

    /**
     * Get REST request body for recent trades.
     */
    static std::string get_trades_request(const std::string& coin = "BTC") {
        return "{\"type\": \"recentTrades\", \"coin\": \"" + coin + "\"}";
    }

    /**
     * Get REST request body for meta and asset contexts (includes funding).
     */
    static std::string get_meta_request() {
        return "{\"type\": \"metaAndAssetCtxs\"}";
    }

    /**
     * Get WebSocket subscription message.
     */
    static std::string get_subscribe_message(const std::string& coin = "BTC") {
        return "{\"method\": \"subscribe\", \"subscription\": {\"type\": \"l2Book\", \"coin\": \"" + coin + "\"}}";
    }

    /**
     * Get heartbeat/ping message.
     */
    static std::string get_heartbeat_message() {
        return "{\"method\": \"ping\"}";
    }

    /**
     * Parse REST l2Book response into OrderBook.
     * Response: {"levels": [[{"px":"...", "sz":"...", "n":...},...], [...]]}
     */
    static bool parse_rest_response(const std::string& json, OrderBook& book) {
        auto start = std::chrono::high_resolution_clock::now();

        book.bids.clear();
        book.asks.clear();
        book.exchange = Exchange::HYPERLIQUID;

        // Find levels array
        size_t levels_pos = json.find("\"levels\"");
        if (levels_pos == std::string::npos) return false;

        size_t arr_start = json.find('[', levels_pos);
        if (arr_start == std::string::npos) return false;

        // Parse bids (first inner array)
        size_t bids_start = json.find('[', arr_start + 1);
        if (bids_start != std::string::npos) {
            size_t bids_end = find_matching_bracket(json, bids_start);
            if (bids_end != std::string::npos) {
                parse_hl_levels(json.substr(bids_start, bids_end - bids_start + 1), book.bids);
            }
        }

        // Parse asks (second inner array after bids)
        size_t bids_end = find_matching_bracket(json, bids_start);
        size_t asks_start = json.find('[', bids_end + 1);
        if (asks_start != std::string::npos) {
            size_t asks_end = find_matching_bracket(json, asks_start);
            if (asks_end != std::string::npos) {
                parse_hl_levels(json.substr(asks_start, asks_end - asks_start + 1), book.asks);
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
        // Check if this is an l2Book update
        if (json.find("\"channel\":\"l2Book\"") == std::string::npos) {
            return false;
        }

        // Find data object and parse same as REST
        size_t data_pos = json.find("\"data\"");
        if (data_pos == std::string::npos) return false;

        return parse_rest_response(json.substr(data_pos), book);
    }

    /**
     * Parse recent trades response to calculate flow imbalance.
     * Returns: {buy_volume, sell_volume, imbalance_pct}
     */
    static std::tuple<double, double, double> parse_trades(const std::string& json) {
        double buy_vol = 0.0, sell_vol = 0.0;

        size_t pos = 0;
        while (pos < json.size()) {
            // Find next trade object
            size_t side_pos = json.find("\"side\"", pos);
            if (side_pos == std::string::npos) break;

            // Get side: "B" for buy, "A" for ask (sell)
            size_t side_val = json.find(':', side_pos) + 1;
            while (side_val < json.size() && (json[side_val] == ' ' || json[side_val] == '"')) side_val++;
            char side = json[side_val];

            // Find px and sz
            size_t px_pos = json.find("\"px\"", side_pos);
            size_t sz_pos = json.find("\"sz\"", side_pos);

            if (px_pos != std::string::npos && sz_pos != std::string::npos) {
                double px = parse_string_number(json, px_pos);
                double sz = parse_string_number(json, sz_pos);
                double notional = px * sz;

                if (side == 'B') {
                    buy_vol += notional;
                } else if (side == 'A') {
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

    // Parse Hyperliquid level format: [{"px":"94000.0","sz":"1.5","n":5}, ...]
    static void parse_hl_levels(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t pos = 0;
        while (pos < arr.size() && levels.size() < MAX_BOOK_LEVELS) {
            // Find object start
            size_t obj_start = arr.find('{', pos);
            if (obj_start == std::string::npos) break;

            size_t obj_end = arr.find('}', obj_start);
            if (obj_end == std::string::npos) break;

            std::string obj = arr.substr(obj_start, obj_end - obj_start + 1);

            // Parse px and sz (they are quoted strings)
            double price = parse_string_number(obj, obj.find("\"px\""));
            double size = parse_string_number(obj, obj.find("\"sz\""));

            if (price > 0.0 && size > 0.0) {
                levels.push_back({price, size});
            }

            pos = obj_end + 1;
        }
    }

    // Parse a quoted number like "px":"94000.5"
    static double parse_string_number(const std::string& s, size_t key_pos) {
        if (key_pos == std::string::npos) return 0.0;

        // Find the value after the colon
        size_t colon = s.find(':', key_pos);
        if (colon == std::string::npos) return 0.0;

        // Skip to quote or digit
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
