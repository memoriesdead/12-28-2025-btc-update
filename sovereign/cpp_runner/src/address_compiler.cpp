/**
 * ADDRESS COMPILER
 * ================
 * Converts SQLite address database to memory-mapped binary format.
 * Run ONCE, then blockchain_runner uses instant mmap loading.
 *
 * Usage:
 *   ./address_compiler --input walletexplorer_addresses.db --output addresses.bin
 *
 * Binary format:
 *   Header (64 bytes): magic, version, counts
 *   Exchange table: 64 bytes per exchange (name)
 *   Address entries: 16 bytes each (hash + exchange_id), SORTED by hash
 */

#include <iostream>
#include <fstream>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <sqlite3.h>

constexpr uint32_t MMAP_MAGIC = 0x41444452;  // "ADDR"
constexpr uint32_t MMAP_VERSION = 1;
constexpr size_t HEADER_SIZE = 64;
constexpr size_t EXCHANGE_ENTRY_SIZE = 64;
constexpr size_t ADDRESS_ENTRY_SIZE = 16;

#pragma pack(push, 1)
struct FileHeader {
    uint32_t magic;
    uint32_t version;
    uint64_t address_count;
    uint32_t exchange_count;
    uint8_t reserved[44];
};

struct AddressEntry {
    uint64_t hash;
    uint16_t exchange_id;
    uint8_t padding[6];
};
#pragma pack(pop)

// FNV-1a hash
uint64_t hash_address(const std::string& addr) {
    uint64_t hash = 14695981039346656037ULL;
    for (char c : addr) {
        hash ^= static_cast<uint64_t>(static_cast<uint8_t>(c));
        hash *= 1099511628211ULL;
    }
    return hash;
}

int main(int argc, char* argv[]) {
    std::string input_db = "/root/sovereign/walletexplorer_addresses.db";
    std::string output_bin = "/root/sovereign/addresses.bin";

    // Parse args
    for (int i = 1; i < argc; i++) {
        if (std::string(argv[i]) == "--input" && i + 1 < argc) {
            input_db = argv[++i];
        } else if (std::string(argv[i]) == "--output" && i + 1 < argc) {
            output_bin = argv[++i];
        }
    }

    std::cout << "========================================" << std::endl;
    std::cout << "ADDRESS COMPILER - SQLite to Binary" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "Input:  " << input_db << std::endl;
    std::cout << "Output: " << output_bin << std::endl;
    std::cout << std::endl;

    auto total_start = std::chrono::high_resolution_clock::now();

    // Open SQLite
    sqlite3* db = nullptr;
    int rc = sqlite3_open_v2(input_db.c_str(), &db, SQLITE_OPEN_READONLY, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open database: " << sqlite3_errmsg(db) << std::endl;
        return 1;
    }

    // First pass: collect unique exchanges
    std::cout << "Pass 1: Collecting exchanges..." << std::endl;
    std::unordered_map<std::string, uint16_t> exchange_to_id;
    std::vector<std::string> exchange_names;

    sqlite3_stmt* stmt = nullptr;
    rc = sqlite3_prepare_v2(db, "SELECT DISTINCT exchange FROM addresses ORDER BY exchange", -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db) << std::endl;
        return 1;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        if (name) {
            uint16_t id = static_cast<uint16_t>(exchange_names.size());
            exchange_to_id[name] = id;
            exchange_names.push_back(name);
        }
    }
    sqlite3_finalize(stmt);

    std::cout << "Found " << exchange_names.size() << " exchanges" << std::endl;

    // Second pass: read all addresses and hash them
    std::cout << "Pass 2: Reading and hashing addresses..." << std::endl;
    auto hash_start = std::chrono::high_resolution_clock::now();

    std::vector<AddressEntry> entries;
    entries.reserve(10000000);  // Reserve for 10M addresses

    rc = sqlite3_prepare_v2(db, "SELECT address, exchange FROM addresses", -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db) << std::endl;
        return 1;
    }

    size_t count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* addr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const char* exchange = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));

        if (addr && exchange) {
            AddressEntry entry{};
            entry.hash = hash_address(addr);
            entry.exchange_id = exchange_to_id[exchange];
            entries.push_back(entry);

            count++;
            if (count % 1000000 == 0) {
                std::cout << "  Processed " << count / 1000000 << "M addresses..." << std::endl;
            }
        }
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    auto hash_end = std::chrono::high_resolution_clock::now();
    auto hash_ms = std::chrono::duration_cast<std::chrono::milliseconds>(hash_end - hash_start).count();
    std::cout << "Hashed " << entries.size() << " addresses in " << hash_ms << " ms" << std::endl;

    // Sort by hash for binary search
    std::cout << "Pass 3: Sorting by hash..." << std::endl;
    auto sort_start = std::chrono::high_resolution_clock::now();

    std::sort(entries.begin(), entries.end(), [](const AddressEntry& a, const AddressEntry& b) {
        return a.hash < b.hash;
    });

    auto sort_end = std::chrono::high_resolution_clock::now();
    auto sort_ms = std::chrono::duration_cast<std::chrono::milliseconds>(sort_end - sort_start).count();
    std::cout << "Sorted in " << sort_ms << " ms" << std::endl;

    // Check for hash collisions (same hash, different addresses would need handling)
    size_t collisions = 0;
    for (size_t i = 1; i < entries.size(); i++) {
        if (entries[i].hash == entries[i-1].hash) {
            collisions++;
        }
    }
    if (collisions > 0) {
        std::cout << "Warning: " << collisions << " hash collisions detected" << std::endl;
    }

    // Write binary file
    std::cout << "Pass 4: Writing binary file..." << std::endl;
    auto write_start = std::chrono::high_resolution_clock::now();

    std::ofstream out(output_bin, std::ios::binary);
    if (!out) {
        std::cerr << "Failed to create output file" << std::endl;
        return 1;
    }

    // Write header
    FileHeader header{};
    header.magic = MMAP_MAGIC;
    header.version = MMAP_VERSION;
    header.address_count = entries.size();
    header.exchange_count = static_cast<uint32_t>(exchange_names.size());
    out.write(reinterpret_cast<const char*>(&header), sizeof(header));

    // Write exchange names (64 bytes each: 1 byte length + 63 bytes name)
    for (const auto& name : exchange_names) {
        uint8_t exchange_entry[EXCHANGE_ENTRY_SIZE] = {};
        exchange_entry[0] = static_cast<uint8_t>(std::min(name.size(), size_t(63)));
        std::memcpy(exchange_entry + 1, name.c_str(), exchange_entry[0]);
        out.write(reinterpret_cast<const char*>(exchange_entry), EXCHANGE_ENTRY_SIZE);
    }

    // Write address entries
    out.write(reinterpret_cast<const char*>(entries.data()), entries.size() * sizeof(AddressEntry));

    out.close();

    auto write_end = std::chrono::high_resolution_clock::now();
    auto write_ms = std::chrono::duration_cast<std::chrono::milliseconds>(write_end - write_start).count();

    // Calculate file size
    size_t file_size = HEADER_SIZE + (exchange_names.size() * EXCHANGE_ENTRY_SIZE) + (entries.size() * ADDRESS_ENTRY_SIZE);

    auto total_end = std::chrono::high_resolution_clock::now();
    auto total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(total_end - total_start).count();

    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "COMPILATION COMPLETE" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "Addresses:    " << entries.size() << std::endl;
    std::cout << "Exchanges:    " << exchange_names.size() << std::endl;
    std::cout << "File size:    " << file_size / (1024 * 1024) << " MB" << std::endl;
    std::cout << "Collisions:   " << collisions << std::endl;
    std::cout << "Total time:   " << total_ms << " ms" << std::endl;
    std::cout << std::endl;
    std::cout << "Binary file ready: " << output_bin << std::endl;
    std::cout << "Blockchain runner will now start INSTANTLY!" << std::endl;

    return 0;
}
