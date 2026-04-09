#!/usr/bin/env bash
set -e

rm -rf build/

PYBIND_DIR=$(python3 -m pybind11 --cmakedir)

if command -v scl &>/dev/null; then
    # Server: activate devtoolset-11 and run cmake within that environment
    scl enable devtoolset-11 -- bash -c "
        cmake -S . -B build -Dpybind11_DIR=$PYBIND_DIR &&
        cmake --build build --parallel 12
    "
else
    # Desktop: activate venv
    source venv/bin/activate
    cmake -S . -B build -Dpybind11_DIR="$PYBIND_DIR"
    cmake --build build --parallel 12
fi
