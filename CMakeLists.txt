cmake_minimum_required(VERSION 3.15)
project(ecc_cpp CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Optimizations
add_compile_options(-O3 -march=native)

# pybind11 — prefer venv install, fall back to system
find_package(pybind11 CONFIG REQUIRED)

# Source files (stub for now; phases 2-5 add more)
set(ECC_SOURCES
    cpp/src/feistel_perm.cpp
    cpp/src/grid_shuffle.cpp
    cpp/src/group_hash.cpp
    cpp/src/hash_dag.cpp
    cpp/src/bitflip_solver.cpp
    cpp/src/bindings.cpp
)

pybind11_add_module(_ecc_cpp ${ECC_SOURCES})

target_include_directories(_ecc_cpp PRIVATE cpp/include)

# Place the built .so next to the Python sources
set_target_properties(_ecc_cpp PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}"
)
