#include "tx_decoder.hpp"
#include <cstring>
#include <array>
#include <algorithm>

// Simple SHA256 implementation (or use OpenSSL in production)
namespace {

// SHA256 constants
constexpr std::array<uint32_t, 64> K = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

inline uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
inline uint32_t ch(uint32_t x, uint32_t y, uint32_t z) { return (x & y) ^ (~x & z); }
inline uint32_t maj(uint32_t x, uint32_t y, uint32_t z) { return (x & y) ^ (x & z) ^ (y & z); }
inline uint32_t sig0(uint32_t x) { return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22); }
inline uint32_t sig1(uint32_t x) { return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25); }
inline uint32_t ep0(uint32_t x) { return rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3); }
inline uint32_t ep1(uint32_t x) { return rotr(x, 17) ^ rotr(x, 19) ^ (x >> 10); }

std::array<uint8_t, 32> sha256(const uint8_t* data, size_t len) {
    std::array<uint32_t, 8> h = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    };

    // Pad message
    size_t orig_len = len;
    size_t padded_len = ((len + 8) / 64 + 1) * 64;
    std::vector<uint8_t> padded(padded_len, 0);
    memcpy(padded.data(), data, len);
    padded[len] = 0x80;

    uint64_t bit_len = static_cast<uint64_t>(orig_len) * 8;
    for (int i = 0; i < 8; ++i) {
        padded[padded_len - 1 - i] = static_cast<uint8_t>(bit_len >> (i * 8));
    }

    // Process blocks
    for (size_t block = 0; block < padded_len; block += 64) {
        std::array<uint32_t, 64> w{};
        for (int i = 0; i < 16; ++i) {
            w[i] = (static_cast<uint32_t>(padded[block + i * 4]) << 24) |
                   (static_cast<uint32_t>(padded[block + i * 4 + 1]) << 16) |
                   (static_cast<uint32_t>(padded[block + i * 4 + 2]) << 8) |
                   (static_cast<uint32_t>(padded[block + i * 4 + 3]));
        }
        for (int i = 16; i < 64; ++i) {
            w[i] = ep1(w[i - 2]) + w[i - 7] + ep0(w[i - 15]) + w[i - 16];
        }

        auto [a, b, c, d, e, f, g, hh] = h;

        for (int i = 0; i < 64; ++i) {
            uint32_t t1 = hh + sig1(e) + ch(e, f, g) + K[i] + w[i];
            uint32_t t2 = sig0(a) + maj(a, b, c);
            hh = g; g = f; f = e; e = d + t1;
            d = c; c = b; b = a; a = t1 + t2;
        }

        h[0] += a; h[1] += b; h[2] += c; h[3] += d;
        h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }

    std::array<uint8_t, 32> result;
    for (int i = 0; i < 8; ++i) {
        result[i * 4] = static_cast<uint8_t>(h[i] >> 24);
        result[i * 4 + 1] = static_cast<uint8_t>(h[i] >> 16);
        result[i * 4 + 2] = static_cast<uint8_t>(h[i] >> 8);
        result[i * 4 + 3] = static_cast<uint8_t>(h[i]);
    }
    return result;
}

std::array<uint8_t, 32> double_sha256(const uint8_t* data, size_t len) {
    auto first = sha256(data, len);
    return sha256(first.data(), 32);
}

// Base58 alphabet
constexpr char BASE58_ALPHABET[] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

std::string base58_encode(const std::vector<uint8_t>& data) {
    std::vector<uint8_t> input(data);
    std::string result;

    // Count leading zeros
    size_t leading_zeros = 0;
    for (size_t i = 0; i < input.size() && input[i] == 0; ++i) {
        ++leading_zeros;
    }

    // Encode
    size_t size = input.size() * 138 / 100 + 1;
    std::vector<uint8_t> output(size, 0);

    for (size_t i = 0; i < input.size(); ++i) {
        int carry = input[i];
        for (size_t j = 0; j < output.size(); ++j) {
            carry += 256 * output[output.size() - 1 - j];
            output[output.size() - 1 - j] = carry % 58;
            carry /= 58;
        }
    }

    // Skip leading zeros in output
    auto it = std::find_if(output.begin(), output.end(), [](uint8_t c) { return c != 0; });

    // Add leading '1's
    result.reserve(leading_zeros + std::distance(it, output.end()));
    result.append(leading_zeros, '1');
    for (; it != output.end(); ++it) {
        result += BASE58_ALPHABET[*it];
    }

    return result;
}

// Bech32 charset
constexpr char BECH32_CHARSET[] = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";

uint32_t bech32_polymod(const std::vector<uint8_t>& values) {
    constexpr uint32_t GEN[] = {0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3};
    uint32_t chk = 1;
    for (uint8_t v : values) {
        uint8_t b = chk >> 25;
        chk = ((chk & 0x1ffffff) << 5) ^ v;
        for (int i = 0; i < 5; ++i) {
            if ((b >> i) & 1) chk ^= GEN[i];
        }
    }
    return chk;
}

std::vector<uint8_t> bech32_hrp_expand(const std::string& hrp) {
    std::vector<uint8_t> result;
    result.reserve(hrp.size() * 2 + 1);
    for (char c : hrp) result.push_back(c >> 5);
    result.push_back(0);
    for (char c : hrp) result.push_back(c & 31);
    return result;
}

std::vector<uint8_t> convert_bits(const uint8_t* data, size_t len, int from, int to, bool pad) {
    std::vector<uint8_t> result;
    int acc = 0;
    int bits = 0;
    int max_v = (1 << to) - 1;

    for (size_t i = 0; i < len; ++i) {
        acc = (acc << from) | data[i];
        bits += from;
        while (bits >= to) {
            bits -= to;
            result.push_back((acc >> bits) & max_v);
        }
    }

    if (pad && bits > 0) {
        result.push_back((acc << (to - bits)) & max_v);
    }

    return result;
}

} // anonymous namespace

uint64_t TxDecoder::read_varint(const uint8_t*& ptr, const uint8_t* end) {
    if (ptr >= end) return 0;

    uint8_t first = *ptr++;
    if (first < 0xfd) return first;
    if (first == 0xfd) {
        if (ptr + 2 > end) return 0;
        uint16_t val = ptr[0] | (static_cast<uint16_t>(ptr[1]) << 8);
        ptr += 2;
        return val;
    }
    if (first == 0xfe) {
        if (ptr + 4 > end) return 0;
        uint32_t val = ptr[0] | (static_cast<uint32_t>(ptr[1]) << 8) |
                       (static_cast<uint32_t>(ptr[2]) << 16) | (static_cast<uint32_t>(ptr[3]) << 24);
        ptr += 4;
        return val;
    }
    if (ptr + 8 > end) return 0;
    uint64_t val = 0;
    for (int i = 0; i < 8; ++i) {
        val |= static_cast<uint64_t>(ptr[i]) << (i * 8);
    }
    ptr += 8;
    return val;
}

std::string TxDecoder::read_hash256_rev(const uint8_t*& ptr) {
    std::string result(64, '0');
    constexpr char hex[] = "0123456789abcdef";
    for (int i = 31; i >= 0; --i) {
        result[(31 - i) * 2] = hex[ptr[i] >> 4];
        result[(31 - i) * 2 + 1] = hex[ptr[i] & 0xf];
    }
    ptr += 32;
    return result;
}

std::string TxDecoder::compute_txid(const uint8_t* data, size_t len) {
    auto hash = double_sha256(data, len);
    std::string result(64, '0');
    constexpr char hex[] = "0123456789abcdef";
    for (int i = 31; i >= 0; --i) {
        result[(31 - i) * 2] = hex[hash[i] >> 4];
        result[(31 - i) * 2 + 1] = hex[hash[i] & 0xf];
    }
    return result;
}

std::string TxDecoder::base58check_encode(uint8_t version, const uint8_t* data, size_t len) {
    std::vector<uint8_t> payload;
    payload.reserve(1 + len + 4);
    payload.push_back(version);
    payload.insert(payload.end(), data, data + len);

    auto checksum = double_sha256(payload.data(), payload.size());
    payload.insert(payload.end(), checksum.begin(), checksum.begin() + 4);

    return base58_encode(payload);
}

std::string TxDecoder::bech32_encode(const std::string& hrp, int witver,
                                      const uint8_t* data, size_t len) {
    auto data5 = convert_bits(data, len, 8, 5, true);
    data5.insert(data5.begin(), witver);

    auto hrp_exp = bech32_hrp_expand(hrp);
    std::vector<uint8_t> combined;
    combined.reserve(hrp_exp.size() + data5.size() + 6);
    combined.insert(combined.end(), hrp_exp.begin(), hrp_exp.end());
    combined.insert(combined.end(), data5.begin(), data5.end());
    combined.insert(combined.end(), 6, 0);

    uint32_t polymod = bech32_polymod(combined) ^ 1;

    std::string result = hrp + "1";
    result.reserve(hrp.size() + 1 + data5.size() + 6);
    for (uint8_t v : data5) {
        result += BECH32_CHARSET[v];
    }
    for (int i = 0; i < 6; ++i) {
        result += BECH32_CHARSET[(polymod >> (5 * (5 - i))) & 31];
    }

    return result;
}

std::optional<std::string> TxDecoder::extract_address(const std::vector<uint8_t>& script) {
    if (script.empty()) return std::nullopt;

    // P2PKH: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
    if (script.size() == 25 && script[0] == 0x76 && script[1] == 0xa9 &&
        script[2] == 0x14 && script[23] == 0x88 && script[24] == 0xac) {
        return base58check_encode(0x00, &script[3], 20);
    }

    // P2SH: OP_HASH160 <20 bytes> OP_EQUAL
    if (script.size() == 23 && script[0] == 0xa9 && script[1] == 0x14 && script[22] == 0x87) {
        return base58check_encode(0x05, &script[2], 20);
    }

    // P2WPKH: OP_0 <20 bytes>
    if (script.size() == 22 && script[0] == 0x00 && script[1] == 0x14) {
        return bech32_encode("bc", 0, &script[2], 20);
    }

    // P2WSH: OP_0 <32 bytes>
    if (script.size() == 34 && script[0] == 0x00 && script[1] == 0x20) {
        return bech32_encode("bc", 0, &script[2], 32);
    }

    // P2TR: OP_1 <32 bytes>
    if (script.size() == 34 && script[0] == 0x51 && script[1] == 0x20) {
        return bech32_encode("bc", 1, &script[2], 32);
    }

    return std::nullopt;
}

std::optional<DecodedTx> TxDecoder::decode(const uint8_t* data, size_t len) {
    if (len < 10) return std::nullopt;

    DecodedTx tx;
    const uint8_t* ptr = data;
    const uint8_t* end = data + len;
    const uint8_t* txid_start = data;

    // Version (4 bytes, little-endian)
    tx.version = ptr[0] | (static_cast<int32_t>(ptr[1]) << 8) |
                 (static_cast<int32_t>(ptr[2]) << 16) | (static_cast<int32_t>(ptr[3]) << 24);
    ptr += 4;

    // Check for segwit marker
    tx.is_segwit = false;
    const uint8_t* witness_start = nullptr;
    if (ptr + 2 <= end && ptr[0] == 0x00 && ptr[1] == 0x01) {
        tx.is_segwit = true;
        ptr += 2;
    }

    // Input count
    uint64_t input_count = read_varint(ptr, end);
    if (input_count > 10000) return std::nullopt;

    tx.inputs.reserve(input_count);
    for (uint64_t i = 0; i < input_count; ++i) {
        if (ptr + 36 > end) return std::nullopt;

        TxInput input;
        input.prev_txid = read_hash256_rev(ptr);
        input.prev_vout = ptr[0] | (static_cast<uint32_t>(ptr[1]) << 8) |
                          (static_cast<uint32_t>(ptr[2]) << 16) | (static_cast<uint32_t>(ptr[3]) << 24);
        ptr += 4;

        uint64_t script_len = read_varint(ptr, end);
        if (ptr + script_len + 4 > end) return std::nullopt;

        input.script_sig.assign(ptr, ptr + script_len);
        ptr += script_len;

        input.sequence = ptr[0] | (static_cast<uint32_t>(ptr[1]) << 8) |
                         (static_cast<uint32_t>(ptr[2]) << 16) | (static_cast<uint32_t>(ptr[3]) << 24);
        ptr += 4;

        tx.inputs.push_back(std::move(input));
    }

    // Output count
    uint64_t output_count = read_varint(ptr, end);
    if (output_count > 10000) return std::nullopt;

    tx.outputs.reserve(output_count);
    for (uint64_t i = 0; i < output_count; ++i) {
        if (ptr + 8 > end) return std::nullopt;

        TxOutput output;
        output.value_sat = 0;
        for (int j = 0; j < 8; ++j) {
            output.value_sat |= static_cast<uint64_t>(ptr[j]) << (j * 8);
        }
        ptr += 8;

        uint64_t script_len = read_varint(ptr, end);
        if (ptr + script_len > end) return std::nullopt;

        output.script_pubkey.assign(ptr, ptr + script_len);
        ptr += script_len;

        tx.outputs.push_back(std::move(output));
    }

    // Skip witness data for segwit
    if (tx.is_segwit) {
        for (uint64_t i = 0; i < input_count; ++i) {
            uint64_t witness_count = read_varint(ptr, end);
            for (uint64_t j = 0; j < witness_count; ++j) {
                uint64_t item_len = read_varint(ptr, end);
                if (ptr + item_len > end) return std::nullopt;
                ptr += item_len;
            }
        }
    }

    // Locktime
    if (ptr + 4 > end) return std::nullopt;
    tx.locktime = ptr[0] | (static_cast<uint32_t>(ptr[1]) << 8) |
                  (static_cast<uint32_t>(ptr[2]) << 16) | (static_cast<uint32_t>(ptr[3]) << 24);

    // Compute txid (for segwit, need to strip witness data)
    if (tx.is_segwit) {
        // Build non-witness serialization for txid
        std::vector<uint8_t> txid_data;
        txid_data.reserve(len);

        // Version
        txid_data.insert(txid_data.end(), data, data + 4);

        // Skip marker/flag, copy inputs and outputs
        const uint8_t* p = data + 6; // Skip version + marker + flag

        // Input count
        uint64_t ic = read_varint(p, end);
        // Re-encode input count
        if (ic < 0xfd) {
            txid_data.push_back(static_cast<uint8_t>(ic));
        } else {
            // Handle larger varints if needed
            txid_data.push_back(static_cast<uint8_t>(ic));
        }

        // Inputs
        for (const auto& inp : tx.inputs) {
            // Prev txid (reversed back)
            for (int i = 31; i >= 0; --i) {
                uint8_t high = (inp.prev_txid[i * 2] >= 'a') ? (inp.prev_txid[i * 2] - 'a' + 10) : (inp.prev_txid[i * 2] - '0');
                uint8_t low = (inp.prev_txid[i * 2 + 1] >= 'a') ? (inp.prev_txid[i * 2 + 1] - 'a' + 10) : (inp.prev_txid[i * 2 + 1] - '0');
                txid_data.push_back((high << 4) | low);
            }
            // Prev vout
            txid_data.push_back(inp.prev_vout & 0xff);
            txid_data.push_back((inp.prev_vout >> 8) & 0xff);
            txid_data.push_back((inp.prev_vout >> 16) & 0xff);
            txid_data.push_back((inp.prev_vout >> 24) & 0xff);
            // Script sig length and data
            txid_data.push_back(static_cast<uint8_t>(inp.script_sig.size()));
            txid_data.insert(txid_data.end(), inp.script_sig.begin(), inp.script_sig.end());
            // Sequence
            txid_data.push_back(inp.sequence & 0xff);
            txid_data.push_back((inp.sequence >> 8) & 0xff);
            txid_data.push_back((inp.sequence >> 16) & 0xff);
            txid_data.push_back((inp.sequence >> 24) & 0xff);
        }

        // Output count
        if (tx.outputs.size() < 0xfd) {
            txid_data.push_back(static_cast<uint8_t>(tx.outputs.size()));
        }

        // Outputs
        for (const auto& out : tx.outputs) {
            for (int i = 0; i < 8; ++i) {
                txid_data.push_back((out.value_sat >> (i * 8)) & 0xff);
            }
            txid_data.push_back(static_cast<uint8_t>(out.script_pubkey.size()));
            txid_data.insert(txid_data.end(), out.script_pubkey.begin(), out.script_pubkey.end());
        }

        // Locktime
        txid_data.push_back(tx.locktime & 0xff);
        txid_data.push_back((tx.locktime >> 8) & 0xff);
        txid_data.push_back((tx.locktime >> 16) & 0xff);
        txid_data.push_back((tx.locktime >> 24) & 0xff);

        tx.txid = compute_txid(txid_data.data(), txid_data.size());
    } else {
        tx.txid = compute_txid(data, len);
    }

    return tx;
}
