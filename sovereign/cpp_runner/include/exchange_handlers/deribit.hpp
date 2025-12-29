/**
 * Deribit Exchange Handler
 *
 * WebSocket: wss://www.deribit.com/ws/api/v2
 * REST: https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-PERPETUAL&depth=50
 * Leverage: 50x (2% initial margin)
 *
 * WebSocket subscribe message:
 * {"jsonrpc":"2.0","id":1,"method":"public/subscribe","params":{"channels":["book.BTC-PERPETUAL.100ms"]}}
 *
 * WebSocket response format:
 * {"jsonrpc":"2.0","method":"subscription","params":{
 *   "channel":"book.BTC-PERPETUAL.100ms",
 *   "data":{"bids":[[price,amount],...],"asks":[[price,amount],...]}
 * }}
 *
 * REST response format:
 * {"jsonrpc":"2.0","result":{
 *   "bids":[[price,amount],...],
 *   "asks":[[price,amount],...]
 * }}
 */

#pragma once

#include "../order_book_types.hpp"
#include <string>
#include <cstdlib>

namespace sovereign {
namespace exchange {

class DeribitHandler {
public:
    static constexpr const char* WS_URL = "wss://www.deribit.com/ws/api/v2";
    static constexpr const char* REST_URL = "https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-PERPETUAL&depth=50";
    static constexpr const char* SYMBOL = "BTC-PERPETUAL";

    /**
     * Get WebSocket subscription message.
     */
    static std::string get_subscribe_message() {
        return R"({"jsonrpc":"2.0","id":1,"method":"public/subscribe","params":{"channels":["book.BTC-PERPETUAL.100ms"]}})";
    }

    /**
     * Get heartbeat message to keep connection alive.
     */
    static std::string get_heartbeat_message() {
        return R"({"jsonrpc":"2.0","id":0,"method":"public/test"})";
    }

    /**
     * Parse WebSocket message into OrderBook.
     */
    static bool parse_ws_message(const std::string& json, OrderBook& book) {
        // Check if this is a book update
        if (json.find("\"channel\":\"book.BTC-PERPETUAL") == std::string::npos) {
            return false;
        }

        // Find data object
        size_t data_pos = json.find("\"data\"");
        if (data_pos == std::string::npos) return false;

        return parse_book_data(json.substr(data_pos), book);
    }

    /**
     * Parse REST response into OrderBook.
     */
    static bool parse_rest_response(const std::string& json, OrderBook& book) {
        // Find result object
        size_t result_pos = json.find("\"result\"");
        if (result_pos == std::string::npos) return false;

        return parse_book_data(json.substr(result_pos), book);
    }

private:
    static bool parse_book_data(const std::string& json, OrderBook& book) {
        book.bids.clear();
        book.asks.clear();

        // Find bids array
        size_t bids_pos = json.find("\"bids\"");
        if (bids_pos != std::string::npos) {
            size_t arr_start = json.find('[', bids_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_numeric_array(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
            }
        }

        // Find asks array
        size_t asks_pos = json.find("\"asks\"");
        if (asks_pos != std::string::npos) {
            size_t arr_start = json.find('[', asks_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_numeric_array(json.substr(arr_start, arr_end - arr_start + 1), book.asks);
            }
        }

        return book.is_valid();
    }

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

    // Parse [[price, amount], ...] format (numeric values)
    static void parse_numeric_array(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t pos = 0;
        while (pos < arr.size() && levels.size() < MAX_BOOK_LEVELS) {
            // Find inner array [price, amount]
            size_t inner_start = arr.find('[', pos);
            if (inner_start == std::string::npos) break;

            size_t inner_end = arr.find(']', inner_start);
            if (inner_end == std::string::npos) break;

            std::string inner = arr.substr(inner_start + 1, inner_end - inner_start - 1);

            // Parse price and amount
            size_t comma = inner.find(',');
            if (comma != std::string::npos) {
                double price = std::strtod(inner.substr(0, comma).c_str(), nullptr);
                double amount = std::strtod(inner.substr(comma + 1).c_str(), nullptr);

                if (price > 0.0 && amount > 0.0) {
                    levels.push_back({price, amount});
                }
            }

            pos = inner_end + 1;
        }
    }
};

} // namespace exchange
} // namespace sovereign
