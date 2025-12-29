/**
 * Poloniex Exchange Handler
 *
 * WebSocket: wss://ws.poloniex.com/ws/public
 * REST: https://api.poloniex.com/markets/BTC_USDT/orderBook?limit=50
 * Leverage: 75x
 *
 * WebSocket subscribe message:
 * {"event":"subscribe","channel":["book"],"symbols":["BTC_USDT"]}
 *
 * WebSocket response format:
 * {"channel":"book","data":[{"symbol":"BTC_USDT","bids":[["price","amount"],...],"asks":[["price","amount"],...]}]}
 *
 * REST response format:
 * {"time":1234567890,"scale":"0.01","bids":["price","amount","price","amount",...],"asks":[...]}
 */

#pragma once

#include "../order_book_types.hpp"
#include <string>
#include <cstdlib>

namespace sovereign {
namespace exchange {

class PoloniexHandler {
public:
    static constexpr const char* WS_URL = "wss://ws.poloniex.com/ws/public";
    static constexpr const char* REST_URL = "https://api.poloniex.com/markets/BTC_USDT/orderBook?limit=50";
    static constexpr const char* SYMBOL = "BTC_USDT";

    /**
     * Get WebSocket subscription message.
     */
    static std::string get_subscribe_message() {
        return R"({"event":"subscribe","channel":["book"],"symbols":["BTC_USDT"]})";
    }

    /**
     * Parse WebSocket message into OrderBook.
     */
    static bool parse_ws_message(const std::string& json, OrderBook& book) {
        // Check if this is a book update
        if (json.find("\"channel\":\"book\"") == std::string::npos) {
            return false;
        }

        // Find data array
        size_t data_pos = json.find("\"data\"");
        if (data_pos == std::string::npos) return false;

        return parse_book_data(json.substr(data_pos), book);
    }

    /**
     * Parse REST response into OrderBook.
     */
    static bool parse_rest_response(const std::string& json, OrderBook& book) {
        book.bids.clear();
        book.asks.clear();

        // Poloniex REST uses flat array: ["price","amount","price","amount",...]
        size_t bids_pos = json.find("\"bids\"");
        if (bids_pos != std::string::npos) {
            size_t arr_start = json.find('[', bids_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_flat_string_array(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
            }
        }

        size_t asks_pos = json.find("\"asks\"");
        if (asks_pos != std::string::npos) {
            size_t arr_start = json.find('[', asks_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_flat_string_array(json.substr(arr_start, arr_end - arr_start + 1), book.asks);
            }
        }

        return book.is_valid();
    }

private:
    static bool parse_book_data(const std::string& json, OrderBook& book) {
        book.bids.clear();
        book.asks.clear();

        // Find bids array (WebSocket uses [["price","amount"],...] format)
        size_t bids_pos = json.find("\"bids\"");
        if (bids_pos != std::string::npos) {
            size_t arr_start = json.find('[', bids_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_string_array(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
            }
        }

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

    // Parse [["price", "amount"], ...] format (string values)
    static void parse_string_array(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t pos = 0;
        while (pos < arr.size() && levels.size() < MAX_BOOK_LEVELS) {
            // Find inner array
            size_t inner_start = arr.find('[', pos);
            if (inner_start == std::string::npos) break;

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

    // Parse ["price","amount","price","amount",...] format (flat array)
    static void parse_flat_string_array(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t pos = 0;
        while (pos < arr.size() && levels.size() < MAX_BOOK_LEVELS) {
            // Find first quoted string (price)
            size_t q1 = arr.find('\"', pos);
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

            pos = q4 + 1;
        }
    }
};

} // namespace exchange
} // namespace sovereign
