#pragma once

#include <string>
#include <vector>
#include <cstdint>
#include <optional>

struct TxInput {
    std::string prev_txid;
    uint32_t prev_vout;
    std::vector<uint8_t> script_sig;
    uint32_t sequence;
};

struct TxOutput {
    uint64_t value_sat;
    std::vector<uint8_t> script_pubkey;
};

struct DecodedTx {
    int32_t version;
    std::vector<TxInput> inputs;
    std::vector<TxOutput> outputs;
    uint32_t locktime;
    std::string txid;
    bool is_segwit;
};

class TxDecoder {
public:
    // Decode raw transaction bytes
    [[nodiscard]] static std::optional<DecodedTx> decode(const uint8_t* data, size_t len);

    // Extract Bitcoin address from output script
    [[nodiscard]] static std::optional<std::string> extract_address(const std::vector<uint8_t>& script);

private:
    // Read variable length integer
    [[nodiscard]] static uint64_t read_varint(const uint8_t*& ptr, const uint8_t* end);

    // Read bytes in reverse (for txid)
    [[nodiscard]] static std::string read_hash256_rev(const uint8_t*& ptr);

    // Compute double SHA256 for txid
    [[nodiscard]] static std::string compute_txid(const uint8_t* data, size_t len);

    // Base58Check encode
    [[nodiscard]] static std::string base58check_encode(uint8_t version, const uint8_t* data, size_t len);

    // Bech32 encode for segwit
    [[nodiscard]] static std::string bech32_encode(const std::string& hrp, int witver,
                                                    const uint8_t* data, size_t len);
};
