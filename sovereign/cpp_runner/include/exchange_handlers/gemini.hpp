/**
 * Gemini Exchange Handler
 *
 * WebSocket: wss://api.gemini.com/v1/marketdata/btcusd
 * REST: https://api.gemini.com/v1/book/btcusd
 * Leverage: 100x (perpetuals)
 *
 * WebSocket format (auto-subscribes):
 * {"type":"update","socket_sequence":0,"events":[
 *   {"type":"change","side":"bid","price":"87000.00","remaining":"0.5","delta":"0.5","reason":"place"}
 * ]}
 *
 * REST format:
 * {"bids":[{"price":"87000.00","amount":"0.5","timestamp":"1234567890"},...],
 *  "asks":[{"price":"87010.00","amount":"0.3","timestamp":"1234567890"},...]}
 */

#pragma once

#include "../order_book_types.hpp"
#include <string>
#include <cstdlib>

namespace sovereign {
namespace exchange {

class GeminiHandler {
public:
    static constexpr const char* WS_URL = "wss://api.gemini.com/v1/marketdata/btcusd";
    static constexpr const char* REST_URL = "https://api.gemini.com/v1/book/btcusd";
    static constexpr const char* SYMBOL = "btcusd";

    /**
     * Get WebSocket subscription message.
     * Gemini auto-subscribes on the marketdata endpoint, no message needed.
     */
    static std::string get_subscribe_message() {
        return "";
    }

    /**
     * Parse WebSocket message into OrderBook.
     */
    static bool parse_ws_message(const std::string& json, OrderBook& book) {
        // Check for initial snapshot or update
        if (json.find("\"type\":\"update\"") != std::string::npos) {
            // Incremental update - for simplicity, we'll request full book periodically
            // In production, maintain local book and apply deltas
            return parse_ws_update(json, book);
        }
        return false;
    }

    /**
     * Parse REST response into OrderBook.
     */
    static bool parse_rest_response(const std::string& json, OrderBook& book) {
        book.bids.clear();
        book.asks.clear();

        // Find bids array
        size_t bids_pos = json.find("\"bids\"");
        if (bids_pos != std::string::npos) {
            size_t arr_start = json.find('[', bids_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_gemini_levels(json.substr(arr_start, arr_end - arr_start + 1), book.bids);
            }
        }

        // Find asks array
        size_t asks_pos = json.find("\"asks\"");
        if (asks_pos != std::string::npos) {
            size_t arr_start = json.find('[', asks_pos);
            size_t arr_end = find_matching_bracket(json, arr_start);
            if (arr_start != std::string::npos && arr_end != std::string::npos) {
                parse_gemini_levels(json.substr(arr_start, arr_end - arr_start + 1), book.asks);
            }
        }

        return book.is_valid();
    }

private:
    static bool parse_ws_update(const std::string& json, OrderBook& book) {
        // For now, just check if it's a valid update
        // TODO: Implement proper incremental book maintenance
        return json.find("\"events\"") != std::string::npos;
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

    static void parse_gemini_levels(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t pos = 0;
        while (pos < arr.size() && levels.size() < MAX_BOOK_LEVELS) {
            // Find price
            size_t price_key = arr.find("\"price\"", pos);
            if (price_key == std::string::npos) break;

            size_t price_start = arr.find('\"', price_key + 7) + 1;
            size_t price_end = arr.find('\"', price_start);
            if (price_start == std::string::npos || price_end == std::string::npos) break;

            double price = std::strtod(arr.substr(price_start, price_end - price_start).c_str(), nullptr);

            // Find amount
            size_t amount_key = arr.find("\"amount\"", price_end);
            if (amount_key == std::string::npos) {
                pos = price_end + 1;
                continue;
            }

            size_t amount_start = arr.find('\"', amount_key + 8) + 1;
            size_t amount_end = arr.find('\"', amount_start);
            if (amount_start == std::string::npos || amount_end == std::string::npos) break;

            double amount = std::strtod(arr.substr(amount_start, amount_end - amount_start).c_str(), nullptr);

            if (price > 0.0 && amount > 0.0) {
                levels.push_back({price, amount});
            }

            pos = amount_end + 1;
        }
    }
};

} // namespace exchange
} // namespace sovereign
