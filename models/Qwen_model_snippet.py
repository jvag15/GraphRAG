"""
Helper loader for Qwen GGUF model via llama-cpp-python.
"""
import os
import torch
from llama_cpp import Llama

def load_qwen_model(qwen_path: str = None) -> Llama:
    """Loads the Qwen LLM using llama-cpp-python."""
    qwen_path = qwen_path or os.environ.get("QWEN_MODEL_PATH", "models/Qwen2.5-7B-Instruct-Q4_K_M.gguf")
    n_threads = int(os.environ.get("LLAMA_N_THREADS", 8))
    n_threads_batch = int(os.environ.get("LLAMA_N_THREADS_BATCH", 8))

    try:
        qwen_llm = Llama(
            model_path=qwen_path,
            n_gpu_layers=-1,   # All layers on GPU
            n_ctx=4096,        # Context size
            n_batch=int(os.environ.get("QWEN_N_BATCH", 512)),
            n_threads=n_threads,
            n_threads_batch=n_threads_batch,
            verbose=False
        )
        print(f"Qwen LLM loaded successfully. Threads: {n_threads}, GPU layers: all (n_gpu_layers=-1)")
        return qwen_llm
    except Exception as e:
        if torch.cuda.is_available():
            vram_used = torch.cuda.memory_allocated(0) / 1e9
            print(f"Error: Failed to load Qwen model. VRAM used: {vram_used:.2f} GB")
        else:
            print("Error: Failed to load Qwen model. CUDA not available.")
        print(f"Exception details: {e}")
        raise RuntimeError(f"Failed to load Qwen model: {e}") from e
