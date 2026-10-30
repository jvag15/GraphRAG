FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3.11 python3-pip python3.11-venv \
    cmake build-essential git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install llama-cpp-python with CUDA support first (long build)
ENV CMAKE_ARGS="-DLLAMA_CUDA=on"
RUN pip3 install llama-cpp-python --no-cache-dir

# Install torch CUDA build
RUN pip3 install torch --index-url https://download.pytorch.org/whl/cu121 --no-cache-dir

COPY requirements.txt .
# Remove llama-cpp-python and torch from requirements.txt before this step
# to avoid re-installing the CPU versions over the GPU ones
RUN pip3 install -r requirements.txt --no-cache-dir

COPY . .

EXPOSE 8000
CMD ["uvicorn", "src.api.fastapi_service:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
