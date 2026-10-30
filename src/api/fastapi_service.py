from dotenv import load_dotenv
load_dotenv()

# Configure PyTorch CUDA allocator to prevent fragmentation and context collision with llama.cpp
import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# src/api/fastapi_service.py
"""
Complete query endpoint implementation for GraphRAG Engine.
Implements the full multi-hop legal query resolution system.
"""

import os
import torch
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from typing import Optional, List
import numpy as np
from llama_cpp import Llama
from pathlib import Path

from src.models import QueryRequest, QueryResponse, ClearSessionRequest, SourceReference
from src.models import QueryAnalysis  # For query_analysis in response
from src.retrieval.hybrid_search import HybridSearchEngine
from src.retrieval.query_router import QueryRouter, strip_thinking
from src.retrieval.reranker import load_reranker, rerank_chunks
from src.api.conversation_manager import ConversationManager

# For Anthropic API (optional)
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None

# Paths to executables and scripts
PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / ("python.exe" if sys.platform == "win32" else "python")
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)
INGESTION_SCRIPT = PROJECT_ROOT / "run_ingestion.py"

# Global instances (loaded once at startup)
search_engine: Optional[HybridSearchEngine] = None
query_router: Optional[QueryRouter] = None
reranker: Optional[object] = None  # CrossEncoder | None
qwen_llm: Optional[object] = None  # Llama | None
conversation_manager: Optional[ConversationManager] = None
anthropic_client: Optional[object] = None
llm_lock: Optional[asyncio.Lock] = None  # Lock for LLM inference to prevent VRAM overflow

# System prompt for Qwen final generation (MODE B — /no_think prepended)
SYSTEM_PROMPT = """You are an elite, literal statutory compliance auditor. Your sole task is to analyze the provided Context (retrieved database text chunks and knowledge graph subgraphs) and output a highly factual compliance answer matching the user's query.

You must execute token generation strictly under these three structural laws:

1. COMPLIANCE GROUNDING (DO NOT INVENT NUMBERS)
- Rely exclusively on facts stated explicitly inside the Context payload.
- If the context does not provide a specific mathematical calculation or exact asset valuation example for the scenario, explain the interplay of the relevant Accounting Standards qualitatively.
- It is strictly forbidden to manufacture example numbers, fabricate domestic loan interest rates, or invent arbitrary asset calculations out of thin air. If it is not written verbatim in the context, do not write it in the output.

2. EXECUTIVE FORMATTING (START DIRECTLY WITH THE ANSWER)
- Output only the clean, final markdown response.
- Start streaming text directly with the core answer data. 
- It is strictly forbidden to include internal reasoning logs, formatting chain-of-thought blocks, scratchpad summaries, planning notes, translation disclaimers, or drafting iterations. 
- To prevent recursive attention loops, proceed lineally through your answer sections. Do not repeat terms, bullet conditions, or introductory phrases redundantly.

3. INLINE CITATION ANCHORING
- Maintain the system's exact inline citation template layer. 
- Place the raw hexadecimal document source chunk ID tokens (for example, [01a8f94847a6c3af]) immediately following the sentence or specific clause they validate.

Context passages:
{context}
"""


def build_sources_list(chunks: List[object]) -> List[SourceReference]:
    """Build sources list for API response from ranked chunks."""
    sources = []
    for chunk in chunks:
        sources.append(SourceReference(
            chunk_id=chunk.chunk_id,
            document_name=os.path.basename(chunk.source_path),
            section_header=chunk.section_header,
            retrieval_method=chunk.retrieval_method,
            relevance_score=chunk.reranker_score
        ))
    return sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load all models and indices on server startup."""
    global search_engine, query_router, reranker, qwen_llm, conversation_manager, anthropic_client

    print("Loading GraphRAG Engine components...")

    # 1. HybridSearchEngine (loads BGE embed + ChromaDB + BM25 + graph)
    search_engine = HybridSearchEngine()
    search_engine.load_indices()

    # 2. Reranker (BGE reranker v2)
    try:
        reranker_path = os.environ["RERANKER_MODEL_PATH"]
        reranker = load_reranker(reranker_path)
        print("Reranker loaded successfully")
    except Exception as e:
        print(f"Warning: Failed to load reranker: {e}")
        reranker = None
    # Inject reranker into search engine and set global
    search_engine.set_reranker(reranker)

    # 3. Qwen LLM (llama-cpp-python) - GGUF file loaded exactly like graph_builder.py
    try:
        qwen_path = os.environ.get("QWEN_MODEL_PATH", str(PROJECT_ROOT / "models" / "Qwen3.6-12B-IQ-Q4_K_M.gguf"))
        n_threads = int(os.environ.get("LLAMA_N_THREADS", 8))
        n_threads_batch = int(os.environ.get("LLAMA_N_THREADS_BATCH", 8))

        qwen_llm = Llama(
            model_path=qwen_path,
            n_gpu_layers=int(os.environ.get("QWEN_N_GPU_LAYERS", -1)),
            n_ctx=8192,
            flash_attn=True,
            type_k=8,
            type_v=8,
            n_batch=int(os.environ.get("QWEN_N_BATCH", 512)),
            n_threads=n_threads,
            n_threads_batch=n_threads_batch,
            verbose=False
        )
        print(f"Qwen LLM loaded successfully. Threads: {n_threads}, GPU layers: all (n_gpu_layers=-1)")
    except Exception as e:
        # Log memory state if CUDA is available
        if torch.cuda.is_available():
            vram_used = torch.cuda.memory_allocated(0) / 1e9
            print(f"Error: Failed to load Qwen model. VRAM used: {vram_used:.2f} GB")
        else:
            print("Error: Failed to load Qwen model. CUDA not available.")
        print(f"Exception details: {e}")
        # Safely abort the server by re-raising the exception
        raise RuntimeError(f"Failed to load Qwen model: {e}") from e

    # 4. ConversationManager
    max_sessions = int(os.environ.get("MAX_SESSIONS", 100))
    max_turns = int(os.environ.get("MAX_TURNS_PER_SESSION", 50))
    conversation_manager = ConversationManager(max_sessions=max_sessions, max_turns_per_session=max_turns)
    print(f"ConversationManager initialized (max_sessions={max_sessions}, max_turns={max_turns})")

    # Create query router using the shared Qwen instance (MODE A: thinking ON)
    global query_router
    query_router = QueryRouter(llama=qwen_llm)
    print(f"Query router initialized with shared Qwen instance.")

    # 5. Anthropic client (initialise but use only when API key is real, not placeholder)
    if ANTHROPIC_AVAILABLE:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key and api_key != "placeholder" and api_key.strip() != "":
            try:
                anthropic_client = anthropic.Anthropic(api_key=api_key)
                print("Anthropic client initialized")
            except Exception as e:
                print(f"Warning: Failed to initialize Anthropic client: {e}")
                anthropic_client = None
        else:
            print("Anthropic API key not provided or is placeholder - using local Qwen only")
            anthropic_client = None
    else:
        print("Anthropic package not available - using local Qwen only")
        anthropic_client = None

    print("GraphRAG Engine fully loaded and ready.")
    global llm_lock
    llm_lock = asyncio.Lock()
    yield

    # Cleanup
    print("Shutting down GraphRAG Engine...")
    # Note: In-memory conversation history is intentionally not persisted


app = FastAPI(title="GraphRAG Engine", lifespan=lifespan)


@app.post("/query", response_model=QueryResponse)
async def query_endpoint(req: QueryRequest):
    """
    Main query endpoint implementing the full multi-hop legal query resolution system.
    Follows the exact 8-step pipeline from QUERY_SYSTEM_SKILL.md Section 6.
    """
    # Validate that we have at least one LLM available
    if qwen_llm is None and anthropic_client is None:
        raise HTTPException(
            status_code=503,
            detail="No LLM available. Neither local Qwen nor Anthropic API is configured."
        )

    # Step 1 — Session management
    session_id = req.session_id
    if not session_id or not conversation_manager.get_session(session_id):
        session_id = conversation_manager.create_session()
    conversation_manager.add_turn(session_id, "user", req.query)

    # Step 2 — Query routing (Qwen, MODE A, thinking ON)
    conversation_summary = conversation_manager.get_summary(session_id)
    # Use local Qwen for routing (required for the system to work)
    if qwen_llm is None:
        raise HTTPException(
            status_code=503,
            detail="Local Qwen model required for query routing but not available"
        )
    # Query router should already be initialized in lifespan
    global query_router
    if query_router is None:
        # Fallback: create router with shared instance (should not happen)
        query_router = QueryRouter(llama=qwen_llm)

    analysis = query_router.analyse(req.query, conversation_summary)
    # Clear GPU cache after query router to prevent conflict with PyTorch embeddings
    torch.cuda.empty_cache()

    # Step 3 — Retrieval (all 3 paths, always)
    # Retrieve more results initially to give reranker plenty to work with
    retrieval_top_k = max(20, req.top_k * 2)  # Get 2x more or at least 20

    # Run retrieval on original query
    original_results = search_engine.search(
        req.query,
        top_k=retrieval_top_k,
        graph_hops=analysis.hop_depth
    )

    # Also run retrieval on each expanded query and merge results
    all_candidates = original_results.ranked_chunks.copy()

    for expanded_query in analysis.expanded_queries:
        if expanded_query.strip() and expanded_query != req.query:
            expanded_results = search_engine.search(
                expanded_query,
                top_k=retrieval_top_k,
                graph_hops=analysis.hop_depth
            )
            # Add unique chunks (by chunk_id)
            existing_ids = {c.chunk_id for c in all_candidates}
            for chunk in expanded_results.ranked_chunks:
                if chunk.chunk_id not in existing_ids:
                    all_candidates.append(chunk)
                    existing_ids.add(chunk.chunk_id)

    # Limit total candidates to prevent excessive processing
    if len(all_candidates) > 50:
        # Sort by original score and take top 50
        all_candidates.sort(key=lambda x: x.score, reverse=True)
        all_candidates = all_candidates[:50]

    # Step 4 — Reranking
    async with llm_lock:
        if reranker is not None and len(all_candidates) > 0:
            try:
                reranked_results, has_sufficient_context = rerank_chunks(
                    reranker, req.query, all_candidates, top_k=req.top_k
                )
            except Exception as e:
                print(f"Warning: Reranking failed: {e}")
                print("Falling back to RRF-only results")
                reranked_results = all_candidates[:req.top_k]
                has_sufficient_context = len(reranked_results) > 0
        else:
            # No reranker or no candidates
            reranked_results = all_candidates[:req.top_k]
            has_sufficient_context = len(reranked_results) > 0

        # Clear GPU cache after reranker to prevent conflict with llama.cpp KV cache
        torch.cuda.empty_cache()

        # Step 5 — Relevance gate
        if not has_sufficient_context:
            no_data_response = (
                "The knowledge base does not currently contain relevant information for this query. "
                "Please consult the relevant act directly or contact a senior partner."
            )
            conversation_manager.add_turn(session_id, "assistant", no_data_response, sources=[])

            return QueryResponse(
                answer=no_data_response,
                sources=[],
                session_id=session_id,
                has_sufficient_context=False,
                query_analysis={
                    "intent": analysis.intent,
                    "legal_entities": analysis.legal_entities,
                    "graph_seed_labels": analysis.graph_seed_labels,
                    "expanded_queries": analysis.expanded_queries,
                    "requires_multi_hop": analysis.requires_multi_hop,
                    "hop_depth": analysis.hop_depth
                } if analysis else None
            )

        # Context assembly with strict length limit to protect the 12GB VRAM buffer
        MAX_CONTEXT_CHARS = 24000
        context_parts = []
        current_length = 0

        for chunk in reranked_results:
            chunk_text = f"[{chunk.chunk_id}] Source: {chunk.source_path}\n{chunk.text}"
            if current_length + len(chunk_text) > MAX_CONTEXT_CHARS:
                break
            context_parts.append(chunk_text)
            current_length += len(chunk_text)

        context = "\n\n---\n\n".join(context_parts)

        # Step 7 — Final generation
        # Choose between Anthropic API (if available and real key) or local Qwen
        # HARD-DISABLE ANTHROPIC to avoid 401 errors and rely strictly on local Qwen
        use_anthropic = False

        if use_anthropic:
            # Use Claude Sonnet via Anthropic API
            try:
                message = anthropic_client.messages.create(
                    model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                    max_tokens=2048,
                    system=SYSTEM_PROMPT.replace("{context}", context),
                    messages=[
                        {"role": "user", "content": req.query}
                    ] + conversation_manager.get_history_for_llm(session_id)[:-1]  # exclude last user turn
                )
                answer = message.content[0].text
            except Exception as e:
                print(f"Warning: Anthropic API failed: {e}")
                print("Falling back to local Qwen")
                use_anthropic = False  # Fallback to local

        if not use_anthropic:
            # Use local Qwen (MODE B: /no_think)
            try:
                prompt_payload_string = f"""System: You are a statutory compliance engine. Synthesize a clean, direct markdown response using only the text facts inside the Context block. Do not output planning steps, drafting logs, or scratchpad sequences. Start your output directly with the core answer data.

Context Data:
{context}

Query: {req.query}

Answer:"""

                # --- HARDENED GENERATION LAYER ---
                response = qwen_llm(
                    prompt=prompt_payload_string,
                    max_tokens=800,           # Set an exact ceiling for response density
                    temperature=0.0,          # Zero out stochastic variance for exact compliance mapping
                    top_p=0.1,
                    repeat_penalty=1.25,      # Increased to break tight structural loops
                    frequency_penalty=0.70,   # High penalty to terminate repeating line states
                    presence_penalty=0.15,
                    stop=[
                        "</think>", 
                        "</USER_COMPLIANCE_QUERY>", 
                        "</USER_QUERY>", 
                        "<USER_COMPLIANCE_QUERY>", 
                        "**Explanation:**",
                        "\n\n\n"
                    ]                         # Absolute stop boundaries to cut off state bleeding instantly
                )
                answer = response["choices"][0]["text"]
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Qwen Generation/Context Error: {str(e)}"
                )

        # Step 8 — Format and return
        sources = build_sources_list(reranked_results)
        conversation_manager.add_turn(session_id, "assistant", answer, sources=[s.dict() for s in sources])

        return QueryResponse(
            answer=answer,
            sources=sources,
            session_id=session_id,
            has_sufficient_context=True,
            query_analysis={
                "intent": analysis.intent,
                "legal_entities": analysis.legal_entities,
                "graph_seed_labels": analysis.graph_seed_labels,
                "expanded_queries": analysis.expanded_queries,
                "requires_multi_hop": analysis.requires_multi_hop,
                "hop_depth": analysis.hop_depth
            } if analysis else None
        )


@app.post("/query/clear", response_model=dict)
async def clear_session(req: ClearSessionRequest):
    """Clear conversation history for a session."""
    if conversation_manager.get_session(req.session_id):
        conversation_manager.delete_session(req.session_id)
        return {"status": "cleared", "session_id": req.session_id}
    else:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/health")
async def health_check():
    """Health check endpoint with model loading status."""
    # Calculate GPU VRAM usage if available
    gpu_vram_used_gb = 0.0
    if torch.cuda.is_available():
        gpu_vram_used_gb = torch.cuda.memory_allocated(0) / 1e9

    return {
        "status": "ok",
        "models_loaded": {
            "search_engine": search_engine is not None,
            "query_router": query_router is not None,
            "reranker": reranker is not None,
            "qwen_llm": qwen_llm is not None,
            "conversation_manager": conversation_manager is not None,
            "anthropic_client": anthropic_client is not None
        },
        "gpu_vram_used_gb": round(gpu_vram_used_gb, 2)
    }


@app.get("/stats")
async def get_stats():
    """Get index statistics."""
    if search_engine is None:
        raise HTTPException(status_code=503, detail="Search engine not loaded")
    return search_engine.get_stats()


@app.post("/ingest")
async def trigger_ingest():
    """Trigger ingestion of files currently in ingestion_mouth/. Runs in background."""
    import subprocess
    import sys
    try:
        subprocess.Popen([str(VENV_PYTHON), str(INGESTION_SCRIPT), "--source", "local"])
        return {"status": "ingestion started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start ingestion: {e}")