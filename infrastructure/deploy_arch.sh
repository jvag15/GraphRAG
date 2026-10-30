#!/bin/bash
# deploy_arch.sh

set -e

echo "==> Installing system dependencies..."
sudo pacman -Syu --noconfirm
sudo pacman -S --noconfirm python python-pip cuda cudnn cmake base-devel git

echo "==> Setting up virtual environment..."
python -m venv venv
source venv/bin/activate

echo "==> Installing llama-cpp-python with CUDA support..."
CMAKE_ARGS="-DLLAMA_CUDA=on" FORCE_CMAKE=1 pip install llama-cpp-python --no-cache-dir

echo "==> Installing PyTorch with CUDA..."
pip install torch --index-url https://download.pytorch.org/whl/cu121 --no-cache-dir

echo "==> Installing remaining dependencies..."
pip install -r requirements.txt --no-cache-dir

echo "==> Downloading BAAI/bge-large-en-v1.5 full model directory..."
huggingface-cli download BAAI/bge-large-en-v1.5 \
  --local-dir models/bge-large-en-v1.5 \
  --local-dir-use-symlinks False

echo "==> Creating directory structure..."
mkdir -p data/bm25_index data/chroma_db ingestion_mouth

echo "==> Setup complete. Drop files into ingestion_mouth/ and run:"
echo "    python run_ingestion.py --source local"
echo "    uvicorn src.api.fastapi_service:app --host 0.0.0.0 --port 8000"
