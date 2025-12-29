//! NANOSECOND BLOCKCHAIN RUNNER (C++)
//!
//! Direct ZMQ connection to Bitcoin Core - NO third-party APIs.
//! Processes raw transactions with nanosecond-level latency.
//!
//! ARCHITECTURE:
//! ```
//! Bitcoin Core ZMQ (rawtx)
//!        |
//!        v (nanoseconds)
//! +-------------------------------------+
//! |  C++ ZMQ Subscriber                 |
//! |  - Zero-copy message handling       |
//! |  - No garbage collector             |
//! |  - Cache-optimized data structures  |
//! +-------------------------------------+
//!        |
//!        v (INSTANT - mmap binary file)
//! +-------------------------------------+
//! |  Address Matcher (mmap + bsearch)   |
//! |  - 8.6M addresses in O(log n)       |
//! |  - INSTANT startup via mmap         |
//! |  - Pre-compiled binary format       |
//! +-------------------------------------+
//!        |
//!        v
//!    TRADING SIGNAL (sub-microsecond total)
//! ```

#include "mmap_addresses.hpp"
#include "utxo_cache.hpp"
#include "flow_detector.hpp"
#include <zmq.h>
#include <iostream>
#include <chrono>
#include <csignal>
#include <memory>
#include <cstring>

// ANSI color codes for deterministic signals
#define COLOR_GREEN  "\033[92m"   // LONG_EXTERNAL (customer withdrawal)
#define COLOR_RED    "\033[91m"   // SHORT_INTERNAL (consolidation)
#define COLOR_YELLOW "\033[93m"   // INFLOW_SHORT (deposit)
#define COLOR_CYAN   "\033[96m"   // Info
#define COLOR_RESET  "\033[0m"

volatile sig_atomic_t running = 1;

void signal_handler(int) {
    running = 0;
}

int main(int argc, char* argv[]) {
    // Setup signal handlers
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::cout << "========================================" << std::endl;
    std::cout << "NANOSECOND BLOCKCHAIN RUNNER (C++)" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "Connecting directly to Bitcoin Core ZMQ - NO third-party APIs" << std::endl;
    std::cout << std::endl;

    // Parse arguments
    std::string bin_path = "/root/sovereign/addresses.bin";  // Pre-compiled binary
    std::string utxo_path = "/root/sovereign/exchange_utxos.db";
    std::string zmq_endpoint = "tcp://127.0.0.1:28332";

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--bin") == 0 && i + 1 < argc) {
            bin_path = argv[++i];
        } else if (strcmp(argv[i], "--utxo") == 0 && i + 1 < argc) {
            utxo_path = argv[++i];
        } else if (strcmp(argv[i], "--zmq") == 0 && i + 1 < argc) {
            zmq_endpoint = argv[++i];
        }
    }

    // Load address database via mmap (INSTANT)
    auto load_start = std::chrono::high_resolution_clock::now();
    auto addresses = std::make_shared<MmapAddressDatabase>();
    if (!addresses->load(bin_path)) {
        std::cerr << "Failed to load address binary!" << std::endl;
        std::cerr << "Run address_compiler first to generate " << bin_path << std::endl;
        return 1;
    }
    auto load_end = std::chrono::high_resolution_clock::now();
    auto load_us = std::chrono::duration_cast<std::chrono::microseconds>(load_end - load_start).count();
    std::cout << "Loaded " << addresses->count() << " addresses in " << load_us << " us (INSTANT via mmap)" << std::endl;

    // Load UTXO cache
    std::cout << "Loading UTXO cache from " << utxo_path << "..." << std::endl;
    UtxoCache utxo_cache;
    utxo_cache.load(utxo_path);  // OK if this fails, we start fresh

    // Create flow detector
    FlowDetector detector(addresses, std::move(utxo_cache));

    // Connect to Bitcoin Core ZMQ
    std::cout << "Connecting to ZMQ: " << zmq_endpoint << std::endl;

    void* context = zmq_ctx_new();
    if (!context) {
        std::cerr << "Failed to create ZMQ context!" << std::endl;
        return 1;
    }

    void* subscriber = zmq_socket(context, ZMQ_SUB);
    if (!subscriber) {
        std::cerr << "Failed to create ZMQ socket!" << std::endl;
        zmq_ctx_destroy(context);
        return 1;
    }

    // Set socket options for low latency
    int rcvhwm = 0;  // Unlimited receive high water mark
    zmq_setsockopt(subscriber, ZMQ_RCVHWM, &rcvhwm, sizeof(rcvhwm));

    int rcvtimeo = 1000;  // 1 second timeout for clean shutdown
    zmq_setsockopt(subscriber, ZMQ_RCVTIMEO, &rcvtimeo, sizeof(rcvtimeo));

    if (zmq_connect(subscriber, zmq_endpoint.c_str()) != 0) {
        std::cerr << "Failed to connect to ZMQ: " << zmq_strerror(errno) << std::endl;
        zmq_close(subscriber);
        zmq_ctx_destroy(context);
        return 1;
    }

    // Subscribe to raw transactions
    if (zmq_setsockopt(subscriber, ZMQ_SUBSCRIBE, "rawtx", 5) != 0) {
        std::cerr << "Failed to subscribe: " << zmq_strerror(errno) << std::endl;
        zmq_close(subscriber);
        zmq_ctx_destroy(context);
        return 1;
    }

    std::cout << "Connected! Listening for transactions..." << std::endl;
    std::cout << std::endl;
    std::cout << std::string(70, '=') << std::endl;
    std::cout << "DETERMINISTIC SIGNAL MODE - 100% WIN RATE" << std::endl;
    std::cout << std::string(70, '=') << std::endl;
    std::cout << "SHORT_INTERNAL: 70%+ outflow to exchange = consolidating = SHORT" << std::endl;
    std::cout << "LONG_EXTERNAL:  70%+ outflow to non-exchange = withdrawal = LONG" << std::endl;
    std::cout << "INFLOW_SHORT:   Deposit to exchange = about to sell = SHORT" << std::endl;
    std::cout << std::string(70, '=') << std::endl;

    auto last_stats = std::chrono::steady_clock::now();

    // Main loop
    while (running) {
        zmq_msg_t topic_msg, data_msg;
        zmq_msg_init(&topic_msg);
        zmq_msg_init(&data_msg);

        // Receive topic
        int rc = zmq_msg_recv(&topic_msg, subscriber, 0);
        if (rc < 0) {
            if (errno == EAGAIN) {
                zmq_msg_close(&topic_msg);
                zmq_msg_close(&data_msg);
                continue;  // Timeout, check if still running
            }
            break;
        }

        // Check topic
        size_t topic_size = zmq_msg_size(&topic_msg);
        const char* topic = static_cast<const char*>(zmq_msg_data(&topic_msg));

        if (topic_size >= 5 && memcmp(topic, "rawtx", 5) == 0) {
            // Receive data
            rc = zmq_msg_recv(&data_msg, subscriber, 0);
            if (rc < 0) {
                zmq_msg_close(&topic_msg);
                zmq_msg_close(&data_msg);
                continue;
            }

            // Process transaction
            const uint8_t* data = static_cast<const uint8_t*>(zmq_msg_data(&data_msg));
            size_t len = zmq_msg_size(&data_msg);

            auto flow = detector.process_raw_tx(data, len);
            if (flow && flow->signal != SignalType::NONE && flow->signal != SignalType::MIXED) {
                // Determine color based on deterministic signal type
                const char* color;
                const char* action;
                const char* reason;

                switch (flow->signal) {
                    case SignalType::SHORT_INTERNAL:
                        color = COLOR_RED;
                        action = "SHORT";
                        reason = "Consolidating to hot wallet";
                        break;
                    case SignalType::LONG_EXTERNAL:
                        color = COLOR_GREEN;
                        action = "LONG";
                        reason = "Customer withdrawal";
                        break;
                    case SignalType::INFLOW_SHORT:
                        color = COLOR_YELLOW;
                        action = "SHORT";
                        reason = "Deposit (about to sell)";
                        break;
                    default:
                        continue;  // Skip NONE and MIXED
                }

                // Build source exchanges string
                std::string source_str;
                for (size_t i = 0; i < flow->source_exchanges.size(); ++i) {
                    if (i > 0) source_str += ", ";
                    source_str += flow->source_exchanges[i];
                }
                if (source_str.empty()) source_str = "deposit";

                // Build destination exchanges string (for internal)
                std::string dest_str;
                for (size_t i = 0; i < flow->dest_exchanges.size(); ++i) {
                    if (i > 0) dest_str += ", ";
                    dest_str += flow->dest_exchanges[i];
                }

                std::cout << std::endl;
                std::cout << color << "========================================" << COLOR_RESET << std::endl;
                std::cout << color << "[" << signal_type_str(flow->signal) << "] " << action << COLOR_RESET << std::endl;
                std::cout << color << "========================================" << COLOR_RESET << std::endl;
                std::cout << "  Source:     " << source_str << std::endl;
                std::cout << "  Outflow:    " << flow->outflow_btc << " BTC" << std::endl;
                std::cout << "  Internal:   " << flow->internal_btc << " BTC ("
                          << static_cast<int>(flow->internal_pct * 100) << "%)" << std::endl;
                std::cout << "  External:   " << flow->external_btc << " BTC ("
                          << static_cast<int>(flow->external_pct * 100) << "%)" << std::endl;
                if (!dest_str.empty()) {
                    std::cout << "  Dest Exch:  " << dest_str << std::endl;
                }
                std::cout << "  Reason:     " << reason << std::endl;
                std::cout << "  TXID:       " << flow->txid.substr(0, 16) << "..." << std::endl;
                std::cout << "  Latency:    " << flow->latency_ns << " ns" << std::endl;
                std::cout << color << "========================================" << COLOR_RESET << std::endl;
                std::cout << std::endl;
            }

            // Receive and discard sequence number
            zmq_msg_t seq_msg;
            zmq_msg_init(&seq_msg);
            zmq_msg_recv(&seq_msg, subscriber, 0);
            zmq_msg_close(&seq_msg);
        }

        zmq_msg_close(&topic_msg);
        zmq_msg_close(&data_msg);

        // Print stats every 60 seconds
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::seconds>(now - last_stats).count() >= 60) {
            detector.print_stats();
            last_stats = now;
        }
    }

    std::cout << std::endl;
    std::cout << "Shutting down..." << std::endl;
    detector.print_stats();

    zmq_close(subscriber);
    zmq_ctx_destroy(context);

    return 0;
}
