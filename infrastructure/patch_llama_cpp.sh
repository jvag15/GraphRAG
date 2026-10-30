#!/bin/bash
# Script to reinstall llama-cpp-python with CUDA support for IQ quantization compatibility
set -e  # Exit on any error

echo "Reinstalling llama-cpp-python with CUDA support..."
CMAKE_ARGS="-DLLAMA_CUDA=on" FORCE_CMAKE=1 pip install --upgrade --force-reinstall llama-cpp-python --no-cache-dir

echo "Reinstallation complete."