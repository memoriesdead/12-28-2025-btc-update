#pragma once

#include <string>
#include <unordered_map>
#include <optional>
#include <cstdint>

struct UtxoInfo {
    uint64_t value_sat;
    std::string exchange;
    std::string address;
};

struct OutpointHash {
    size_t operator()(const std::pair<std::string, uint32_t>& p) const noexcept {
        // FNV-1a hash combining txid and vout
        size_t hash = 14695981039346656037ULL;
        for (char c : p.first) {
            hash ^= static_cast<size_t>(c);
            hash *= 1099511628211ULL;
        }
        hash ^= static_cast<size_t>(p.second);
        hash *= 1099511628211ULL;
        return hash;
    }
};

class UtxoCache {
public:
    UtxoCache() = default;

    // Load existing UTXOs from SQLite
    bool load(const std::string& db_path);

    // Add new UTXO (output to exchange)
    inline void add(const std::string& txid, uint32_t vout,
                   uint64_t value_sat, const std::string& exchange,
                   const std::string& address) {
        cache_[{txid, vout}] = {value_sat, exchange, address};
    }

    // Spend UTXO (input from exchange)
    [[nodiscard]] std::optional<UtxoInfo> spend(const std::string& txid, uint32_t vout) {
        auto it = cache_.find({txid, vout});
        if (it != cache_.end()) {
            UtxoInfo info = std::move(it->second);
            cache_.erase(it);
            return info;
        }
        return std::nullopt;
    }

    [[nodiscard]] size_t size() const noexcept { return cache_.size(); }

private:
    std::unordered_map<std::pair<std::string, uint32_t>, UtxoInfo, OutpointHash> cache_;
};
