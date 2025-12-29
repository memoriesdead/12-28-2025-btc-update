/**
 * Order Book Cache - Thread-Safe In-Memory Cache
 *
 * PURE DATA. NO MOCK. MATH NEVER LIES.
 *
 * This provides a thread-safe cache for order books from multiple exchanges.
 * Uses std::shared_mutex for reader-writer locking:
 * - Multiple concurrent readers (signal processing)
 * - Single writer at a time (WebSocket/REST updates)
 *
 * MULTI-INSTRUMENT SUPPORT:
 * - Caches ALL 7 instrument types per exchange
 * - Key format: "exchange:instrument_type"
 * - Each instrument has its own InstrumentData (mark price, funding, Greeks, etc.)
 *
 * Lock contention is minimal because:
 * - Writes are staggered (100ms-1s per exchange)
 * - Reads are <1 microsecond
 * - Writes hold lock for ~1-5 microseconds
 */

#pragma once

#include "order_book_types.hpp"
#include <array>
#include <shared_mutex>
#include <mutex>
#include <functional>
#include <unordered_map>
#include <string>
#include <vector>

namespace sovereign {

class OrderBookCache {
public:
    // Callback type for update notifications
    using UpdateCallback = std::function<void(Exchange, const OrderBook&)>;

    OrderBookCache() = default;

    // Disable copy (mutexes are not copyable)
    OrderBookCache(const OrderBookCache&) = delete;
    OrderBookCache& operator=(const OrderBookCache&) = delete;

    // ========================================================================
    // READ OPERATIONS (use shared_lock - multiple readers allowed)
    // ========================================================================

    /**
     * Get a copy of the order book for an exchange.
     * Thread-safe: Uses shared_lock (multiple concurrent readers).
     * Performance: <500 nanoseconds typical.
     */
    OrderBook get(Exchange exchange) const {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return OrderBook{};
        }
        std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
        return books_[idx];
    }

    /**
     * Get a reference to bids only (avoids copying asks).
     * Caller must hold the returned lock until done reading.
     */
    std::pair<const std::vector<PriceLevel>&, std::shared_lock<std::shared_mutex>>
    get_bids(Exchange exchange) const {
        size_t idx = static_cast<size_t>(exchange);
        std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
        return {books_[idx].bids, std::move(lock)};
    }

    /**
     * Get a reference to asks only (avoids copying bids).
     */
    std::pair<const std::vector<PriceLevel>&, std::shared_lock<std::shared_mutex>>
    get_asks(Exchange exchange) const {
        size_t idx = static_cast<size_t>(exchange);
        std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
        return {books_[idx].asks, std::move(lock)};
    }

    /**
     * Check if order book is stale (older than max_age_ms).
     */
    bool is_stale(Exchange exchange, int max_age_ms = 5000) const {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return true;
        }
        std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
        return books_[idx].age_ms() > max_age_ms;
    }

    /**
     * Check if order book is valid (has data).
     */
    bool is_valid(Exchange exchange) const {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return false;
        }
        std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
        return books_[idx].is_valid();
    }

    /**
     * Get sequence number for change detection.
     * Lock-free read using atomic.
     */
    uint64_t get_sequence(Exchange exchange) const {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return 0;
        }
        return sequence_counters_[idx].load(std::memory_order_acquire);
    }

    /**
     * Get best bid price.
     */
    double get_best_bid(Exchange exchange) const {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return 0.0;
        }
        std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
        return books_[idx].best_bid();
    }

    /**
     * Get best ask price.
     */
    double get_best_ask(Exchange exchange) const {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return 0.0;
        }
        std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
        return books_[idx].best_ask();
    }

    /**
     * Get total bid depth.
     */
    double get_bid_depth(Exchange exchange, size_t max_levels = 50) const {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return 0.0;
        }
        std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
        return books_[idx].total_bid_depth(max_levels);
    }

    /**
     * Get all order books at once (for monitoring).
     */
    std::array<OrderBook, static_cast<size_t>(Exchange::COUNT)> get_all() const {
        std::array<OrderBook, static_cast<size_t>(Exchange::COUNT)> result;
        for (size_t i = 0; i < static_cast<size_t>(Exchange::COUNT); ++i) {
            std::shared_lock<std::shared_mutex> lock(mutexes_[i]);
            result[i] = books_[i];
        }
        return result;
    }

    // ========================================================================
    // WRITE OPERATIONS (use unique_lock - single writer)
    // ========================================================================

    /**
     * Update order book for an exchange.
     * Thread-safe: Uses unique_lock (exclusive access).
     * Automatically updates timestamp and sequence.
     */
    void update(Exchange exchange, OrderBook&& book) {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return;
        }

        book.timestamp = std::chrono::steady_clock::now();

        {
            std::unique_lock<std::shared_mutex> lock(mutexes_[idx]);
            uint64_t new_seq = sequence_counters_[idx].load() + 1;
            sequence_counters_[idx].store(new_seq);
            book.sequence = new_seq;
            books_[idx] = std::move(book);
        }

        // Fire callback outside lock
        if (update_callback_) {
            std::shared_lock<std::shared_mutex> lock(mutexes_[idx]);
            update_callback_(exchange, books_[idx]);
        }
    }

    /**
     * Update just the bids (for incremental updates).
     */
    void update_bids(Exchange exchange, std::vector<PriceLevel>&& bids) {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return;
        }

        std::unique_lock<std::shared_mutex> lock(mutexes_[idx]);
        books_[idx].bids = std::move(bids);
        books_[idx].timestamp = std::chrono::steady_clock::now();
        books_[idx].sequence = sequence_counters_[idx].fetch_add(1) + 1;
    }

    /**
     * Update just the asks (for incremental updates).
     */
    void update_asks(Exchange exchange, std::vector<PriceLevel>&& asks) {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return;
        }

        std::unique_lock<std::shared_mutex> lock(mutexes_[idx]);
        books_[idx].asks = std::move(asks);
        books_[idx].timestamp = std::chrono::steady_clock::now();
        books_[idx].sequence = sequence_counters_[idx].fetch_add(1) + 1;
    }

    /**
     * Clear order book for an exchange.
     */
    void clear(Exchange exchange) {
        size_t idx = static_cast<size_t>(exchange);
        if (idx >= static_cast<size_t>(Exchange::COUNT)) {
            return;
        }

        std::unique_lock<std::shared_mutex> lock(mutexes_[idx]);
        books_[idx].clear();
        books_[idx].sequence = sequence_counters_[idx].fetch_add(1) + 1;
    }

    /**
     * Clear all order books.
     */
    void clear_all() {
        for (size_t i = 0; i < static_cast<size_t>(Exchange::COUNT); ++i) {
            std::unique_lock<std::shared_mutex> lock(mutexes_[i]);
            books_[i].clear();
            books_[i].sequence = sequence_counters_[i].fetch_add(1) + 1;
        }
    }

    // ========================================================================
    // CALLBACK MANAGEMENT
    // ========================================================================

    /**
     * Set callback for book updates (optional, for monitoring).
     * Called after each update with the new book data.
     */
    void set_update_callback(UpdateCallback callback) {
        update_callback_ = std::move(callback);
    }

    // ========================================================================
    // STATUS/MONITORING
    // ========================================================================

    /**
     * Get number of valid (non-empty) books.
     */
    size_t valid_count() const {
        size_t count = 0;
        for (size_t i = 0; i < static_cast<size_t>(Exchange::COUNT); ++i) {
            std::shared_lock<std::shared_mutex> lock(mutexes_[i]);
            if (books_[i].is_valid()) {
                ++count;
            }
        }
        return count;
    }

    /**
     * Get number of non-stale books.
     */
    size_t fresh_count(int max_age_ms = 5000) const {
        size_t count = 0;
        for (size_t i = 0; i < static_cast<size_t>(Exchange::COUNT); ++i) {
            std::shared_lock<std::shared_mutex> lock(mutexes_[i]);
            if (books_[i].is_valid() && books_[i].age_ms() <= max_age_ms) {
                ++count;
            }
        }
        return count;
    }

    /**
     * Print cache status (for debugging).
     */
    void print_status() const {
        for (size_t i = 0; i < static_cast<size_t>(Exchange::COUNT); ++i) {
            Exchange ex = static_cast<Exchange>(i);
            std::shared_lock<std::shared_mutex> lock(mutexes_[i]);
            const auto& book = books_[i];

            printf("[%s] Bids: %zu | Asks: %zu | Best: $%.2f / $%.2f | "
                   "Depth: %.2f BTC | Age: %ldms | Seq: %lu\n",
                   exchange_name(ex),
                   book.bids.size(),
                   book.asks.size(),
                   book.best_bid(),
                   book.best_ask(),
                   book.total_bid_depth(),
                   book.age_ms(),
                   sequence_counters_[i].load());
        }
    }

private:
    // Per-exchange mutexes (mutable for const read methods)
    mutable std::array<std::shared_mutex, static_cast<size_t>(Exchange::COUNT)> mutexes_;

    // Order book storage
    std::array<OrderBook, static_cast<size_t>(Exchange::COUNT)> books_;

    // Sequence counters for change detection (atomic for lock-free reads)
    std::array<std::atomic<uint64_t>, static_cast<size_t>(Exchange::COUNT)> sequence_counters_{};

    // Optional update callback
    UpdateCallback update_callback_;
};


// ============================================================================
// MULTI-INSTRUMENT CACHE
// ============================================================================
// Caches InstrumentData for ALL 7 instrument types across ALL 110 exchanges.
// Key format: "exchange:instrument_type" (e.g., "binance:perpetual")
// Thread-safe using std::shared_mutex.
// ============================================================================

class InstrumentCache {
public:
    // Callback type for update notifications
    using UpdateCallback = std::function<void(Exchange, InstrumentType, const InstrumentData&)>;

    InstrumentCache() = default;

    // Disable copy (mutexes are not copyable)
    InstrumentCache(const InstrumentCache&) = delete;
    InstrumentCache& operator=(const InstrumentCache&) = delete;

    // ========================================================================
    // CACHE KEY GENERATION
    // ========================================================================

    /**
     * Generate cache key from exchange + instrument type.
     * Format: "exchange_index:instrument_index"
     */
    static size_t make_key(Exchange ex, InstrumentType type) {
        return static_cast<size_t>(ex) * static_cast<size_t>(InstrumentType::INST_COUNT)
             + static_cast<size_t>(type);
    }

    /**
     * Get string representation of key (for debugging).
     */
    static std::string make_key_string(Exchange ex, InstrumentType type) {
        return std::string(exchange_name(ex)) + ":" + instrument_name(type);
    }

    // ========================================================================
    // READ OPERATIONS (use shared_lock - multiple readers allowed)
    // ========================================================================

    /**
     * Get instrument data for exchange + type.
     * Thread-safe: Uses shared_lock.
     * Performance: <1 microsecond typical.
     */
    InstrumentData get(Exchange ex, InstrumentType type) const {
        size_t key = make_key(ex, type);
        std::shared_lock<std::shared_mutex> lock(mutex_);
        auto it = cache_.find(key);
        if (it != cache_.end()) {
            return it->second;
        }
        return InstrumentData{};
    }

    /**
     * Get all instruments for an exchange.
     */
    std::vector<InstrumentData> get_all_instruments(Exchange ex) const {
        std::vector<InstrumentData> result;
        std::shared_lock<std::shared_mutex> lock(mutex_);

        for (size_t i = 0; i < static_cast<size_t>(InstrumentType::INST_COUNT); ++i) {
            size_t key = make_key(ex, static_cast<InstrumentType>(i));
            auto it = cache_.find(key);
            if (it != cache_.end() && it->second.is_valid()) {
                result.push_back(it->second);
            }
        }
        return result;
    }

    /**
     * Get order book for specific instrument.
     */
    OrderBook get_book(Exchange ex, InstrumentType type) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        if (it != cache_.end()) {
            return it->second.book;
        }
        return OrderBook{};
    }

    /**
     * Check if instrument data is stale.
     */
    bool is_stale(Exchange ex, InstrumentType type, int max_age_ms = 5000) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        if (it == cache_.end()) {
            return true;
        }
        return it->second.age_ms() > max_age_ms;
    }

    /**
     * Check if instrument data is fresh (valid and not stale).
     */
    bool is_fresh(Exchange ex, InstrumentType type, int max_age_ms = 5000) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        if (it == cache_.end()) {
            return false;
        }
        return it->second.is_valid() && it->second.age_ms() <= max_age_ms;
    }

    /**
     * Check if exchange supports instrument type.
     */
    bool has_instrument(Exchange ex, InstrumentType type) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        return it != cache_.end() && it->second.is_valid();
    }

    /**
     * Get best bid for instrument.
     */
    double get_best_bid(Exchange ex, InstrumentType type) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        if (it != cache_.end()) {
            return it->second.book.best_bid();
        }
        return 0.0;
    }

    /**
     * Get best ask for instrument.
     */
    double get_best_ask(Exchange ex, InstrumentType type) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        if (it != cache_.end()) {
            return it->second.book.best_ask();
        }
        return 0.0;
    }

    /**
     * Get mark price (for perpetual/futures/inverse).
     */
    double get_mark_price(Exchange ex, InstrumentType type) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        if (it != cache_.end()) {
            return it->second.mark_price;
        }
        return 0.0;
    }

    /**
     * Get funding rate (for perpetual/inverse).
     */
    double get_funding_rate(Exchange ex, InstrumentType type) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        if (it != cache_.end()) {
            return it->second.funding_rate;
        }
        return 0.0;
    }

    /**
     * Get sequence number for change detection.
     */
    uint64_t get_sequence(Exchange ex, InstrumentType type) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t key = make_key(ex, type);
        auto it = cache_.find(key);
        if (it != cache_.end()) {
            return it->second.sequence;
        }
        return 0;
    }

    // ========================================================================
    // WRITE OPERATIONS (use unique_lock - single writer)
    // ========================================================================

    /**
     * Update instrument data.
     * Thread-safe: Uses unique_lock.
     */
    void update(Exchange ex, InstrumentType type, InstrumentData&& data) {
        data.type = type;
        data.timestamp = std::chrono::steady_clock::now();

        size_t key = make_key(ex, type);
        {
            std::unique_lock<std::shared_mutex> lock(mutex_);
            data.sequence = ++global_sequence_;
            cache_[key] = std::move(data);
        }

        // Fire callback outside lock
        if (update_callback_) {
            std::shared_lock<std::shared_mutex> lock(mutex_);
            auto it = cache_.find(key);
            if (it != cache_.end()) {
                update_callback_(ex, type, it->second);
            }
        }
    }

    /**
     * Update just the order book for an instrument.
     */
    void update_book(Exchange ex, InstrumentType type, OrderBook&& book) {
        size_t key = make_key(ex, type);
        std::unique_lock<std::shared_mutex> lock(mutex_);

        auto& data = cache_[key];
        data.type = type;
        data.book = std::move(book);
        data.book.timestamp = std::chrono::steady_clock::now();
        data.timestamp = data.book.timestamp;
        data.last_price = data.book.mid_price();
        data.sequence = ++global_sequence_;
    }

    /**
     * Update funding rate (for perpetual/inverse).
     */
    void update_funding(Exchange ex, InstrumentType type,
                        double funding_rate, int64_t next_funding_ts) {
        size_t key = make_key(ex, type);
        std::unique_lock<std::shared_mutex> lock(mutex_);

        auto& data = cache_[key];
        data.type = type;
        data.funding_rate = funding_rate;
        data.next_funding_ts = next_funding_ts;
        data.timestamp = std::chrono::steady_clock::now();
        data.sequence = ++global_sequence_;
    }

    /**
     * Update mark price (for perpetual/futures/inverse).
     */
    void update_mark_price(Exchange ex, InstrumentType type,
                           double mark_price, double index_price = 0.0) {
        size_t key = make_key(ex, type);
        std::unique_lock<std::shared_mutex> lock(mutex_);

        auto& data = cache_[key];
        data.type = type;
        data.mark_price = mark_price;
        if (index_price > 0) {
            data.index_price = index_price;
        }
        data.timestamp = std::chrono::steady_clock::now();
        data.sequence = ++global_sequence_;
    }

    /**
     * Update options Greeks.
     */
    void update_greeks(Exchange ex, double strike, bool is_call,
                       double delta, double gamma, double theta, double vega,
                       double implied_vol = 0.0) {
        size_t key = make_key(ex, InstrumentType::OPTIONS);
        std::unique_lock<std::shared_mutex> lock(mutex_);

        auto& data = cache_[key];
        data.type = InstrumentType::OPTIONS;
        data.strike = strike;
        data.is_call = is_call;
        data.delta = delta;
        data.gamma = gamma;
        data.theta = theta;
        data.vega = vega;
        if (implied_vol > 0) {
            data.implied_vol = implied_vol;
        }
        data.timestamp = std::chrono::steady_clock::now();
        data.sequence = ++global_sequence_;
    }

    /**
     * Batch update multiple instruments.
     */
    void update_batch(Exchange ex, std::vector<InstrumentData>&& instruments) {
        std::unique_lock<std::shared_mutex> lock(mutex_);
        auto now = std::chrono::steady_clock::now();

        for (auto& data : instruments) {
            data.timestamp = now;
            data.sequence = ++global_sequence_;
            size_t key = make_key(ex, data.type);
            cache_[key] = std::move(data);
        }
    }

    /**
     * Clear instrument data for exchange + type.
     */
    void clear(Exchange ex, InstrumentType type) {
        size_t key = make_key(ex, type);
        std::unique_lock<std::shared_mutex> lock(mutex_);
        cache_.erase(key);
    }

    /**
     * Clear all instruments for an exchange.
     */
    void clear_exchange(Exchange ex) {
        std::unique_lock<std::shared_mutex> lock(mutex_);
        for (size_t i = 0; i < static_cast<size_t>(InstrumentType::INST_COUNT); ++i) {
            size_t key = make_key(ex, static_cast<InstrumentType>(i));
            cache_.erase(key);
        }
    }

    /**
     * Clear all cached data.
     */
    void clear_all() {
        std::unique_lock<std::shared_mutex> lock(mutex_);
        cache_.clear();
    }

    // ========================================================================
    // CALLBACK MANAGEMENT
    // ========================================================================

    /**
     * Set callback for instrument updates.
     */
    void set_update_callback(UpdateCallback callback) {
        update_callback_ = std::move(callback);
    }

    // ========================================================================
    // STATUS/MONITORING
    // ========================================================================

    /**
     * Get total number of cached instruments.
     */
    size_t size() const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        return cache_.size();
    }

    /**
     * Get number of valid instruments for an exchange.
     */
    size_t instrument_count(Exchange ex) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t count = 0;
        for (size_t i = 0; i < static_cast<size_t>(InstrumentType::INST_COUNT); ++i) {
            size_t key = make_key(ex, static_cast<InstrumentType>(i));
            auto it = cache_.find(key);
            if (it != cache_.end() && it->second.is_valid()) {
                ++count;
            }
        }
        return count;
    }

    /**
     * Get number of fresh instruments across all exchanges.
     */
    size_t fresh_count(int max_age_ms = 5000) const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        size_t count = 0;
        for (const auto& [key, data] : cache_) {
            if (data.is_valid() && data.age_ms() <= max_age_ms) {
                ++count;
            }
        }
        return count;
    }

    /**
     * Print cache status (for debugging).
     */
    void print_status() const {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        printf("[INSTRUMENT CACHE] Total: %zu entries\n", cache_.size());

        for (size_t ex_idx = 0; ex_idx < static_cast<size_t>(Exchange::COUNT); ++ex_idx) {
            Exchange ex = static_cast<Exchange>(ex_idx);
            bool has_any = false;

            for (size_t inst_idx = 0; inst_idx < static_cast<size_t>(InstrumentType::INST_COUNT); ++inst_idx) {
                size_t key = make_key(ex, static_cast<InstrumentType>(inst_idx));
                auto it = cache_.find(key);
                if (it != cache_.end() && it->second.is_valid()) {
                    if (!has_any) {
                        printf("  %s:\n", exchange_name(ex));
                        has_any = true;
                    }
                    const auto& data = it->second;
                    printf("    %s: $%.2f | bid=$%.2f ask=$%.2f | age=%ldms\n",
                           instrument_name(data.type),
                           data.last_price,
                           data.book.best_bid(),
                           data.book.best_ask(),
                           data.age_ms());
                }
            }
        }
    }

private:
    // Single mutex for entire cache (simpler than per-key locking)
    mutable std::shared_mutex mutex_;

    // Cache storage: key = (exchange_idx * INST_COUNT + inst_idx)
    std::unordered_map<size_t, InstrumentData> cache_;

    // Global sequence counter for change detection
    uint64_t global_sequence_ = 0;

    // Optional update callback
    UpdateCallback update_callback_;
};

} // namespace sovereign
