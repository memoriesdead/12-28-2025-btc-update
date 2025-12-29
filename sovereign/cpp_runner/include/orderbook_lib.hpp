/**
 * Order Book Library - Public API
 *
 * PURE DATA. NO MOCK. MATH NEVER LIES.
 *
 * This header exposes the public API for the order book library.
 */

#pragma once

namespace sovereign {

// Version and build info
const char* get_version();
const char* get_build_info();

// Global initialization/cleanup
bool initialize();
void cleanup();

// Utility functions
void print_exchange_info();
void benchmark_impact_calculator(int iterations = 100000);

} // namespace sovereign
