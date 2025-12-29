#include "utxo_cache.hpp"
#include <sqlite3.h>
#include <chrono>
#include <iostream>

bool UtxoCache::load(const std::string& db_path) {
    auto start = std::chrono::high_resolution_clock::now();

    sqlite3* db = nullptr;
    int rc = sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Warning: Could not open UTXO cache: " << sqlite3_errmsg(db) << std::endl;
        std::cerr << "Starting with empty cache" << std::endl;
        return false;
    }

    sqlite3_stmt* stmt = nullptr;
    const char* sql = "SELECT txid, vout, value_sat, exchange, address FROM utxos";
    rc = sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Warning: Could not prepare UTXO query: " << sqlite3_errmsg(db) << std::endl;
        sqlite3_close(db);
        return false;
    }

    cache_.reserve(1000000);

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        const char* txid = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        uint32_t vout = static_cast<uint32_t>(sqlite3_column_int(stmt, 1));
        int64_t value = sqlite3_column_int64(stmt, 2);
        const char* exchange = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* address = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));

        if (txid && exchange && address) {
            cache_[{std::string(txid), vout}] = {
                static_cast<uint64_t>(value),
                std::string(exchange),
                std::string(address)
            };
        }
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);

    auto end = std::chrono::high_resolution_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(end - start);

    std::cout << "Loaded " << cache_.size() << " UTXOs in " << elapsed.count() << " ms" << std::endl;

    return true;
}
