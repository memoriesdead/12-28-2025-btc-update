cmake_minimum_required(VERSION 3.16)
project(sovereign_orderbook VERSION 1.0.0 LANGUAGES CXX)

# ============================================================================
# C++ STANDARD AND OPTIMIZATION
# ============================================================================

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Optimization flags for release builds
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -DNDEBUG -flto")
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0 -DDEBUG")

# Default to Release if not specified
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")

# ============================================================================
# FIND DEPENDENCIES
# ============================================================================

# Required
find_package(CURL REQUIRED)
find_package(Threads REQUIRED)

# SQLite3 (for address database)
find_library(SQLITE3_LIBRARY NAMES sqlite3)
find_path(SQLITE3_INCLUDE_DIR sqlite3.h)
if(SQLITE3_LIBRARY)
    message(STATUS "Found SQLite3: ${SQLITE3_LIBRARY}")
else()
    message(FATAL_ERROR "SQLite3 not found - required for blockchain_runner")
endif()

# libwebsockets
find_library(LWS_LIBRARY NAMES websockets)
find_path(LWS_INCLUDE_DIR libwebsockets.h)

if(NOT LWS_LIBRARY)
    message(WARNING "libwebsockets not found - WebSocket support disabled")
    set(HAS_WEBSOCKET OFF)
else()
    message(STATUS "Found libwebsockets: ${LWS_LIBRARY}")
    set(HAS_WEBSOCKET ON)
endif()

# ZMQ (for blockchain runner)
find_package(PkgConfig)
if(PkgConfig_FOUND)
    pkg_check_modules(ZMQ libzmq)
endif()

if(NOT ZMQ_FOUND)
    find_library(ZMQ_LIBRARIES NAMES zmq)
    find_path(ZMQ_INCLUDE_DIRS zmq.h)
    if(ZMQ_LIBRARIES)
        set(ZMQ_FOUND TRUE)
    endif()
endif()

if(ZMQ_FOUND)
    message(STATUS "Found ZMQ: ${ZMQ_LIBRARIES}")
else()
    message(WARNING "ZMQ not found - blockchain_runner will not be built")
endif()

# simdjson (optional, header-only)
find_path(SIMDJSON_INCLUDE_DIR simdjson.h PATHS ${CMAKE_CURRENT_SOURCE_DIR}/include)
if(SIMDJSON_INCLUDE_DIR)
    message(STATUS "Found simdjson: ${SIMDJSON_INCLUDE_DIR}")
    set(HAS_SIMDJSON ON)
else()
    message(STATUS "simdjson not found - using basic JSON parsing")
    set(HAS_SIMDJSON OFF)
endif()

# ============================================================================
# ORDER BOOK LIBRARY
# ============================================================================

add_library(orderbook STATIC
    src/orderbook_lib.cpp
)

target_include_directories(orderbook PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CURL_INCLUDE_DIRS}
)

target_link_libraries(orderbook PUBLIC
    ${CURL_LIBRARIES}
    Threads::Threads
)

if(HAS_WEBSOCKET)
    target_include_directories(orderbook PUBLIC ${LWS_INCLUDE_DIR})
    target_link_libraries(orderbook PUBLIC ${LWS_LIBRARY})
    target_compile_definitions(orderbook PUBLIC HAS_WEBSOCKET=1)
endif()

if(HAS_SIMDJSON)
    target_compile_definitions(orderbook PUBLIC HAS_SIMDJSON=1)
endif()

# ============================================================================
# STANDALONE TEST EXECUTABLE
# ============================================================================

add_executable(test_orderbook
    src/test_main.cpp
)

target_link_libraries(test_orderbook
    orderbook
)

# ============================================================================
# ORDER BOOK SERVICE EXECUTABLE
# ============================================================================

add_executable(orderbook_service
    src/orderbook_service.cpp
)

target_link_libraries(orderbook_service
    orderbook
)

# ============================================================================
# BLOCKCHAIN RUNNER EXECUTABLE (Real-time ZMQ signals)
# ============================================================================

if(ZMQ_FOUND)
    add_executable(blockchain_runner
        src/main.cpp
        src/flow_detector.cpp
        src/tx_decoder.cpp
        src/utxo_cache.cpp
        src/address_database.cpp
    )

    target_include_directories(blockchain_runner PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${ZMQ_INCLUDE_DIRS}
        ${SQLITE3_INCLUDE_DIR}
    )

    target_link_libraries(blockchain_runner
        ${ZMQ_LIBRARIES}
        ${SQLITE3_LIBRARY}
        Threads::Threads
    )

    message(STATUS "blockchain_runner target enabled")
else()
    message(WARNING "blockchain_runner target DISABLED - ZMQ not found")
endif()

# ============================================================================
# INSTALLATION
# ============================================================================

install(TARGETS orderbook test_orderbook orderbook_service
    RUNTIME DESTINATION bin
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)

if(ZMQ_FOUND)
    install(TARGETS blockchain_runner
        RUNTIME DESTINATION bin
    )
endif()

install(DIRECTORY include/
    DESTINATION include/sovereign
)

# ============================================================================
# BUILD INFO
# ============================================================================

message(STATUS "")
message(STATUS "=== SOVEREIGN ORDER BOOK BUILD CONFIG ===")
message(STATUS "Build type:         ${CMAKE_BUILD_TYPE}")
message(STATUS "C++ standard:       ${CMAKE_CXX_STANDARD}")
message(STATUS "WebSocket:          ${HAS_WEBSOCKET}")
message(STATUS "simdjson:           ${HAS_SIMDJSON}")
message(STATUS "CURL:               ${CURL_LIBRARIES}")
message(STATUS "SQLite3:            ${SQLITE3_LIBRARY}")
message(STATUS "ZMQ:                ${ZMQ_FOUND}")
message(STATUS "blockchain_runner:  ${ZMQ_FOUND}")
message(STATUS "==========================================")
message(STATUS "")
