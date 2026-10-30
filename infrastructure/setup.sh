#!/bin/bash
# setup.sh

python -m venv venv
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate
source venv/bin/activate

# MANDATORY: set before installing llama-cpp-python
export CMAKE_ARGS="-DLLAMA_CUDA=on"
export FORCE_CMAKE=1
pip install llama-cpp-python --no-cache-dir

pip install torch --index-url https://download.pytorch.org/whl/cu121 --no-cache-dir
pip install -r requirements.txt --no-cache-dir

huggingface-cli download BAAI/bge-large-en-v1.5 \
  --local-dir models/bge-large-en-v1.5 \
  --local-dir-use-symlinks False

mkdir -p data/bm25_index data/chroma_db ingestion_mouth
cp .env.example .env
echo "Edit .env and add your ANTHROPIC_API_KEY before starting."
