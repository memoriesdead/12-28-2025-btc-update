#pragma once

#include <string>
#include <unordered_map>
#include <unordered_set>
#include <chrono>
#include <iostream>

// Use robin_hood or absl flat_hash_map for production
// For now, std::unordered_map with good hash

struct StringHash {
    using is_transparent = void;

    size_t operator()(const std::string& s) const noexcept {
        // FNV-1a hash - fast and good distribution
        size_t hash = 14695981039346656037ULL;
        for (char c : s) {
            hash ^= static_cast<size_t>(c);
            hash *= 1099511628211ULL;
        }
        return hash;
    }

    size_t operator()(std::string_view s) const noexcept {
        size_t hash = 14695981039346656037ULL;
        for (char c : s) {
            hash ^= static_cast<size_t>(c);
            hash *= 1099511628211ULL;
        }
        return hash;
    }
};

class AddressDatabase {
public:
    AddressDatabase() = default;

    // Load addresses from SQLite database
    bool load(const std::string& db_path);

    // O(1) lookup - is this an exchange address?
    [[nodiscard]] inline bool is_exchange(const std::string& address) const noexcept {
        return exchange_addresses_.find(address) != exchange_addresses_.end();
    }

    // O(1) lookup - which exchange?
    [[nodiscard]] inline const std::string* get_exchange(const std::string& address) const noexcept {
        auto it = address_to_exchange_.find(address);
        return it != address_to_exchange_.end() ? &it->second : nullptr;
    }

    [[nodiscard]] size_t count() const noexcept { return count_; }

private:
    std::unordered_map<std::string, std::string, StringHash> address_to_exchange_;
    std::unordered_set<std::string, StringHash> exchange_addresses_;
    size_t count_ = 0;
};
