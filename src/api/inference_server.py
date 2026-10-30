"""
Llama-3 inference server. Used only during ingestion for entity extraction.
Not needed at query time — queries use Claude via Anthropic API.
"""

from fastapi import FastAPI
from pydantic import BaseModel
from llama_cpp import Llama
from contextlib import asynccontextmanager
import os


llm_instance = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global llm_instance
    llm_instance = Llama(
        model_path=os.environ["LLAMA_MODEL_PATH"],
        n_gpu_layers=int(os.environ.get("LLAMA_N_GPU_LAYERS", -1)),
        n_ctx=int(os.environ.get("LLAMA_N_CTX", 4096)),
        n_batch=int(os.environ.get("LLAMA_N_BATCH", 512)),
        verbose=True
    )
    print("Llama model loaded.")
    yield
    del llm_instance

app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    messages: list[dict]
    max_tokens: int = 1024
    temperature: float = 0.0


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    response = llm_instance.create_chat_completion(
        messages=req.messages,
        max_tokens=req.max_tokens,
        temperature=req.temperature
    )
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": llm_instance is not None}
