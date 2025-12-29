#pragma once

#include <string>
#include <string_view>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

// Binary file format:
// Header (64 bytes):
//   [magic:4][version:4][addr_count:8][exchange_count:4][reserved:44]
// Exchange table:
//   [name_len:1][name:63] x exchange_count (64 bytes each)
// Address entries (sorted by hash):
//   [hash:8][exchange_id:2] x addr_count (10 bytes each, padded to 16)

constexpr uint32_t MMAP_MAGIC = 0x41444452;  // "ADDR"
constexpr uint32_t MMAP_VERSION = 1;
constexpr size_t HEADER_SIZE = 64;
constexpr size_t EXCHANGE_ENTRY_SIZE = 64;
constexpr size_t ADDRESS_ENTRY_SIZE = 16;  // 8 hash + 2 id + 6 padding

struct FileHeader {
    uint32_t magic;
    uint32_t version;
    uint64_t address_count;
    uint32_t exchange_count;
    uint8_t reserved[44];
} __attribute__((packed));

struct AddressEntry {
    uint64_t hash;
    uint16_t exchange_id;
    uint8_t padding[6];
} __attribute__((packed));

static_assert(sizeof(FileHeader) == HEADER_SIZE, "Header size mismatch");
static_assert(sizeof(AddressEntry) == ADDRESS_ENTRY_SIZE, "Entry size mismatch");

class MmapAddressDatabase {
public:
    MmapAddressDatabase() = default;
    ~MmapAddressDatabase() { unload(); }

    // FNV-1a hash - same as before
    static uint64_t hash_address(std::string_view addr) noexcept {
        uint64_t hash = 14695981039346656037ULL;
        for (char c : addr) {
            hash ^= static_cast<uint64_t>(static_cast<uint8_t>(c));
            hash *= 1099511628211ULL;
        }
        return hash;
    }

    // Load via mmap - INSTANT
    bool load(const std::string& bin_path) {
        fd_ = open(bin_path.c_str(), O_RDONLY);
        if (fd_ < 0) {
            std::cerr << "Failed to open " << bin_path << std::endl;
            return false;
        }

        struct stat st;
        if (fstat(fd_, &st) < 0) {
            std::cerr << "Failed to stat file" << std::endl;
            close(fd_);
            return false;
        }
        file_size_ = st.st_size;

        // mmap the entire file
        data_ = static_cast<uint8_t*>(mmap(nullptr, file_size_, PROT_READ, MAP_PRIVATE, fd_, 0));
        if (data_ == MAP_FAILED) {
            std::cerr << "mmap failed" << std::endl;
            close(fd_);
            return false;
        }

        // Advise kernel we'll access sequentially during init, then randomly
        madvise(data_, file_size_, MADV_WILLNEED);

        // Parse header
        header_ = reinterpret_cast<const FileHeader*>(data_);
        if (header_->magic != MMAP_MAGIC || header_->version != MMAP_VERSION) {
            std::cerr << "Invalid binary file format" << std::endl;
            unload();
            return false;
        }

        // Point to exchange names
        exchange_names_ = data_ + HEADER_SIZE;
        exchange_count_ = header_->exchange_count;

        // Point to address entries
        size_t exchange_table_size = exchange_count_ * EXCHANGE_ENTRY_SIZE;
        entries_ = reinterpret_cast<const AddressEntry*>(data_ + HEADER_SIZE + exchange_table_size);
        entry_count_ = header_->address_count;

        std::cout << "Loaded " << entry_count_ << " addresses via mmap (INSTANT)" << std::endl;
        return true;
    }

    void unload() {
        if (data_ && data_ != MAP_FAILED) {
            munmap(data_, file_size_);
            data_ = nullptr;
        }
        if (fd_ >= 0) {
            close(fd_);
            fd_ = -1;
        }
    }

    // O(log n) binary search - still extremely fast with mmap
    [[nodiscard]] inline bool is_exchange(std::string_view address) const noexcept {
        return find_exchange_id(address) != UINT16_MAX;
    }

    // O(log n) lookup - returns exchange name or nullptr
    [[nodiscard]] const char* get_exchange(std::string_view address) const noexcept {
        uint16_t id = find_exchange_id(address);
        if (id == UINT16_MAX) return nullptr;
        return get_exchange_name(id);
    }

    [[nodiscard]] size_t count() const noexcept { return entry_count_; }

private:
    [[nodiscard]] uint16_t find_exchange_id(std::string_view address) const noexcept {
        uint64_t h = hash_address(address);

        // Binary search on sorted entries
        size_t left = 0;
        size_t right = entry_count_;

        while (left < right) {
            size_t mid = left + (right - left) / 2;
            uint64_t mid_hash = entries_[mid].hash;

            if (mid_hash == h) {
                return entries_[mid].exchange_id;
            } else if (mid_hash < h) {
                left = mid + 1;
            } else {
                right = mid;
            }
        }

        return UINT16_MAX;  // Not found
    }

    [[nodiscard]] const char* get_exchange_name(uint16_t id) const noexcept {
        if (id >= exchange_count_) return nullptr;
        const uint8_t* entry = exchange_names_ + (id * EXCHANGE_ENTRY_SIZE);
        // First byte is length, rest is name
        return reinterpret_cast<const char*>(entry + 1);
    }

    int fd_ = -1;
    uint8_t* data_ = nullptr;
    size_t file_size_ = 0;

    const FileHeader* header_ = nullptr;
    const uint8_t* exchange_names_ = nullptr;
    const AddressEntry* entries_ = nullptr;
    size_t entry_count_ = 0;
    uint32_t exchange_count_ = 0;
};
