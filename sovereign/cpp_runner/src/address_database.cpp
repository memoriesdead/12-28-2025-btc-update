#include "address_database.hpp"
#include <sqlite3.h>
#include <chrono>

bool AddressDatabase::load(const std::string& db_path) {
    auto start = std::chrono::high_resolution_clock::now();

    sqlite3* db = nullptr;
    int rc = sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open database: " << sqlite3_errmsg(db) << std::endl;
        return false;
    }

    // Prepare statement
    sqlite3_stmt* stmt = nullptr;
    const char* sql = "SELECT address, exchange FROM addresses";
    rc = sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db) << std::endl;
        sqlite3_close(db);
        return false;
    }

    // Reserve space for ~8.6M addresses
    address_to_exchange_.reserve(9000000);
    exchange_addresses_.reserve(9000000);

    // Fetch all rows
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        const char* addr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const char* exchange = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));

        if (addr && exchange) {
            std::string addr_str(addr);
            std::string exchange_str(exchange);
            exchange_addresses_.insert(addr_str);
            address_to_exchange_.emplace(std::move(addr_str), std::move(exchange_str));
        }
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);

    count_ = address_to_exchange_.size();

    auto end = std::chrono::high_resolution_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(end - start);

    std::cout << "Loaded " << count_ << " addresses in " << elapsed.count() << " ms ("
              << static_cast<double>(count_) / (elapsed.count() / 1000.0) << " addr/sec)" << std::endl;

    return true;
}
