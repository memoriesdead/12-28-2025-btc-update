/**
 * MEXC Exchange Handler
 *
 * WebSocket: wss://wbs.mexc.com/ws
 * REST: https://api.mexc.com/api/v3/depth?symbol=BTCUSDT&limit=50
 * Leverage: 500x (highest available)
 *
 * WebSocket subscribe message:
 * {"method":"SUBSCRIPTION","params":["spot@public.limit.depth.v3.api@BTCUSDT@20"]}
 *
 * WebSocket response format:
 * {"c":"spot@public.limit.depth.v3.api@BTCUSDT@20","d":{"bids":[["price","amount"],...],"asks":[["price","amount"],...]},"t":1234567890}
 *
 * REST response format:
 * {"lastUpdateId":123456,"bids":[["87000.00","0.5"],...],"asks":[["87010.00","0.3"],...]}
 */

#pragma once

#include "../order_book_types.hpp"
#include <string>
#include <cstdlib>

namespace sovereign {
namespace exchange {

class MexcHandler {
public:
    static constexpr const char* WS_URL = "wss://wbs.mexc.com/ws";
    static constexpr const char* REST_URL = "https://api.mexc.com/api/v3/depth?symbol=BTCUSDT&limit=50";
    static constexpr const char* SYMBOL = "BTCUSDT";

    /**
     * Get WebSocket subscription message.
     */
    static std::string get_subscribe_message() {
        return R"({"method":"SUBSCRIPTION","params":["spot@public.limit.depth.v3.api@BTCUSDT@20"]})";
    }

    /**
     * Parse WebSocket message into OrderBook.
     */
    static bool parse_ws_message(const std::string& json, OrderBook& book) {
        // Check if this is a depth update
        if (json.find("\"c\":\"spot@public.limit.depth") == std::string::npos) {
            return false;
        }

        // Find data object (key "d")
        size_t data_pos = json.find("\"d\"");
        if (data_pos == std::string::npos) return false;

        return parse_book_data(json.substr(data_pos), book);
    }

    /**
     * Parse REST response into OrderBook.
     */
    static bool parse_rest_response(const std::string& json, OrderBook& book) {
        return parse_book_data(json, book);
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
                parse_string_array(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
            }
        }

        // Find asks array
        size_t asks_pos = json.find("\"asks\"");
        if (asks_pos != std::string::npos) {
            size_t arr_start = json.find('[', asks_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_string_array(json.substr(arr_start, arr_end - arr_start + 1), book.asks);
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

    // Parse [["price", "amount"], ...] format (string values, MEXC style)
    static void parse_string_array(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t pos = 0;
        while (pos < arr.size() && levels.size() < MAX_BOOK_LEVELS) {
            // Find inner array
            size_t inner_start = arr.find('[', pos);
            if (inner_start == std::string::npos) break;

            // Skip if we're at the outer array start
            if (inner_start == 0) {
                pos = 1;
                continue;
            }

            // Find first quoted string (price)
            size_t q1 = arr.find('\"', inner_start);
            if (q1 == std::string::npos) break;
            size_t q2 = arr.find('\"', q1 + 1);
            if (q2 == std::string::npos) break;

            double price = std::strtod(arr.substr(q1 + 1, q2 - q1 - 1).c_str(), nullptr);

            // Find second quoted string (amount)
            size_t q3 = arr.find('\"', q2 + 1);
            if (q3 == std::string::npos) break;
            size_t q4 = arr.find('\"', q3 + 1);
            if (q4 == std::string::npos) break;

            double amount = std::strtod(arr.substr(q3 + 1, q4 - q3 - 1).c_str(), nullptr);

            if (price > 0.0 && amount > 0.0) {
                levels.push_back({price, amount});
            }

            size_t inner_end = arr.find(']', q4);
            pos = (inner_end != std::string::npos) ? inner_end + 1 : arr.size();
        }
    }
};

} // namespace exchange
} // namespace sovereign
