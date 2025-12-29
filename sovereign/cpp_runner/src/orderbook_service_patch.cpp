    // Main loop
    auto last_write = std::chrono::steady_clock::now();

    while (g_running) {
        // Only read stdin in stdin_mode
        if (stdin_mode) {
            std::string line;
            if (std::getline(std::cin, line)) {
                if (!line.empty()) {
                    process_stdin_signal(handler, line);
                }
            } else {
                // stdin closed, exit stdin mode
                break;
            }
        }

        // Write cache periodically
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_write).count();

        if (elapsed >= interval_ms) {
            write_cache_json(cache, output_path);
            cache.print_status();
            last_write = now;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
