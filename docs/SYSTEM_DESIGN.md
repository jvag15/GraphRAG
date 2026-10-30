# GraphRAG Engine — Master Context File

# For Claude Code and any new AI agent session

# Last updated: June 30, 2026

# SUPERSEDES: All previous versions of this file and GRAPHRAG_SKILL.md

# This revision absorbs CLAUDE_UPDATES_2026-06-20.md (Phase 2) and

# CLAUDE_UPDATES_2026-06-29.md (Phase 3) in full. Both update logs are now

# considered closed and historical — their content lives here and in

# CLAUDE.md going forward. Do not create new CLAUDE_UPDATES_*.md entries

# referencing Phase 2 or Phase 3; only Phase 4 onward

---

## 0. READ THIS FIRST

This document is the single source of truth for the GraphRAG Engine project.
Before writing a single line of code, read this entire file.
Every architectural decision, every change, every outcome is logged here.
Do not make assumptions. Do not reference GRAPHRAG_SKILL.md for model names or
prefixes — that document is outdated. This file supersedes it.

Also read in order after this file: CLAUDE.md, AGENTS.md, ROUTINES.md.
If anything in those files conflicts with this one, CLAUDE.md wins on project
rules; this file wins on historical context and change log.

---

## 1. Project Identity

**Project:** GraphRAG Engine
**Owner:** GraphRAG Platform (CA/Audit firm)
**Purpose:** Indian CA/audit legal research assistant. Ingests GST Act, Income Tax Act,
ICAI circulars, FEMA documents, CA annexures. Returns cited, auditable answers.
**Deployment:** Arch Linux server (SSH access). Windows dev machine (Antigravity IDE).
**Frontend:** PyQt6 desktop GUI running natively on Arch Linux GNOME. gui/ directory.
**Future production:** Local query system is for testing. System will eventually hook
into the company's main website and server. Local GUI is operator/testing only.

---

## 2. Hardware — Server (Arch Linux, deployment target)

| Component | Spec | Notes |
|---|---|---|
| CPU | Intel Xeon W-2125 | 4 cores / 8 threads, ~4.0GHz. Bottleneck for parsing. |
| RAM | 32GB DDR4 | Sequential processing underutilises this intentionally. |
| GPU | NVIDIA GeForce RTX 3060 | 12GB VRAM (shows as 12.5GB in torch). Primary compute. |
| OS | Arch Linux | Python managed via pyenv 3.11.9. System python is 3.14 — DO NOT USE. |
| Storage | 476GB SSD (system) + 932GB HDD | HDD mounted at /mnt/parameter-archives |
| CUDA | 13.3.0 | Installed via pacman. nvcc at /opt/cuda/bin/. Source /etc/profile after install. |
| Python | 3.11.9 via pyenv | venv at /home/graphrag-automation/graphrag_engine/venv/ |

**CPU governor:** Set to `performance` via cpupower. Persist with `systemctl enable cpupower`.
This resolved the 14% CPU cap — now reaches 49-75% during parsing.

**Memory allocator (mandatory for long ingestion runs):**

```bash
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

Install: `sudo pacman -S jemalloc`
Required because glibc malloc cannot handle ML tensor allocations over 50+ hours
without fragmenting. This was discovered after Exit Code -6 (SIGABRT) crashes.

---

## 3. Hardware — Dev Machine (Windows, Antigravity IDE)

| Component | Spec |
|---|---|
| CPU | Ryzen 7 250 AI |
| GPU | RTX 5050 8GB VRAM |
| RAM | 16GB |
| OS | Windows 11 |
| Project root | graphrag_engine\ |

**Critical:** Do NOT confuse dev machine (RTX 5050 8GB) with server (RTX 3060 12GB).
All deployment targets the server. Dev machine is for code editing only.
Claude Code CWD must be graphrag_engine\ — not C:\Users\...

---

## 4. Two-Port Architecture (CRITICAL — understand before touching anything)

The project runs two separate Python HTTP servers at different times:

**Port 8000 — Query Server** (FastAPI, query time only)

- Loads: BGE embed (1.34GB) + Reranker (1.1GB) + Qwen (7.0GB) = ~10.4GB VRAM
- Used by: auditors, PyQt6 GUI, run_eval.py
- Start: `uvicorn src.api.fastapi_service:app --host 0.0.0.0 --port 8000`

**Port 8080 — LLM Inference Server** (llama-cpp-python server, ingestion time only)

- Loads: Llama 3.1 8B Q8_0 = ~8.5GB VRAM
- Used by: graph_builder.py during Stage 3 entity extraction
- Start: `python -m llama_cpp.server --model $LLAMA_MODEL_PATH --host 127.0.0.1 --port 8080`
- Kill if stuck: `pkill -9 -f llama_cpp.server`

**These two servers must NEVER run simultaneously. 12GB VRAM budget.**

This two-port architecture was the fix for Exit Code -11 (SIGSEGV) crashes caused
by PyTorch (BGE embedding) and llama.cpp (entity extraction) colliding in VRAM when
loaded in the same Python process.

---

## 5. Project File Structure

```
/home/graphrag-automation/graphrag_engine/
├── data/
│   ├── bm25_index/bm25.pkl
│   ├── chroma_db/              ← ChromaDB persistent storage (1024-dim BGE vectors)
│   ├── knowledge_graph.json    ← NetworkX MultiDiGraph serialised via orjson
│   └── ingestion_log.json      ← SHA256-based dedup tracker
├── gui/                        ← PyQt6 desktop frontend
│   ├── __init__.py
│   ├── assets/
│   │   └── fonts/               ← Cormorant Garamond, DM Sans, DM Mono .ttf (Phase 4)
│   ├── main.py                  ← Main window, three-pane layout (BUILT)
│   ├── state/
│   │   └── state_manager.py    ← Atomic JSON IPC, PID liveness via psutil (BUILT)
│   ├── services/
│   │   ├── __init__.py
│   │   └── server_manager.py    ← Uvicorn lifecycle, port 8000 auto-launch (BUILT)
│   ├── tabs/
│   │   ├── ingestion_tab.py    ← Controls, telemetry, live log (BUILT)
│   │   ├── query_tab.py        ← Chat, model selector, graph, sources (BUILT)
│   │   └── knowledge_tab.py    ← Archive table, prune action (BUILT)
│   ├── widgets/
│   │   ├── spell_edit.py        ← Live spellchecker (BUILT)
│   │   ├── graph_view.py        ← PyVis QWebEngineView (BUILT)
│   │   ├── mutual_exclusion_dialog.py ← VRAM/lock conflict modal (BUILT)
│   │   └── accordion_message.py ← Collapsible AI response (BUILT)
│   ├── workers/
│   │   ├── ingestion_worker.py  ← batch_coordinator subprocess QThread, PID-tracked
│   │   ├── pruning_worker.py    ← prune_document.py subprocess QThread, PID-tracked
│   │   ├── query_worker.py      ← HTTP POST to port 8000 QThread
│   │   └── telemetry_worker.py  ← pynvml + psutil hardware polling, PID liveness
│   └── styles/
│       └── theme.qss            ← Phase 4: GraphRAG brand tokens (was Catppuccin Mocha)
├── ingestion_mouth/            ← Drop input files here (local mode)
├── logs/
│   └── ingestion_metrics.csv   ← Telemetry data appended during ingestion
├── models/
│   ├── bge-large-en-v1.5/      ← FULL directory (not single .safetensors file)
│   ├── bge-reranker-v2-m3/     ← Cross-encoder reranker
│   └── Qwen3.6-12B-IQ-Q4_K_M.gguf ← Query routing + local generation (testing)
|   └── Meta-Llama-3.1-8B-Instruct-Q8_0.gguf ← Entity Extraction Model
├── query_eso/                  ← 4 JSON eval suites, 25 questions each
│   ├── graphrag_test_suite_vol_1.json
│   ├── graphrag_test_suite_vol_2.json
│   ├── graphrag_test_suite_vol_3.json
│   ├── graphrag_test_suite_vol_4.json
│   └── results/                ← Eval output. Confirmed baseline: 100/100.
├── src/
│   ├── __init__.py             ← REQUIRED — was missing, caused ModuleNotFoundError
│   ├── models.py               ← Shared data types. ALL modules import from here.
│   ├── api/
│   │   ├── __init__.py
│   │   ├── conversation_manager.py
│   │   ├── fastapi_service.py  ← Query API on port 8000. Uses Qwen local or cloud API.
│   │   └── inference_server.py ← Standalone Llama HTTP wrapper on port 8080.
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── graph_builder.py    ← Entity extraction via HTTP POST to port 8080.
│   │   ├── graph_io.py         ← save_graph/load_graph only. NO llama_cpp import.
│   │   ├── keyword_index.py    ← BM25Okapi sparse index.
│   │   └── vector_embed.py     ← BGE-large embeddings → ChromaDB.
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── parser.py           ← File → Chunk objects. strategy="fast". Auto-quarantines bad files.
│   │   ├── sharepoint_client.py
│   │   └── tracker.py          ← SHA256 dedup + pipeline stage tracking.
│   └── retrieval/
│       ├── __init__.py
│       ├── hybrid_search.py    ← 3-path retrieval + RRF fusion + reranker.
│       ├── query_router.py     ← Qwen query analysis (thinking mode ON).
│       └── reranker.py         ← BGE cross-encoder reranking.
├── systemd_configs/
│   ├── graphrag_ingest.service
│   ├── graphrag_ingest_24_7.timer
│   └── graphrag_ingest_nightly.timer
├── .env                        ← chmod 444. Never scp-overwrite.
├── prune_document.py           ← Standalone 4-step pruning script (ChromaDB → BM25 → graph → file move)
├── batch_coordinator.py        ← Fault-tolerant batch pipeline. BATCH_SIZE=1. Emits [TELEMETRY] lines.
├── mock_api.py                 ← Local Windows dummy server for GUI testing.
├── run_ingestion.py            ← CLI entry point. Orchestrates all pipeline stages. Auto-quarantine.
├── run_eval.py                 ← Evaluation runner (100 questions, 4 files).
├── setup_storage_tiers.py
├── sync_sharepoint.py
└── telemetry_dashboard.py      ← Live ingestion monitoring (ETA, token rate).
```

**Critical:** All `__init__.py` files must exist in every src/ subdirectory.
Without them Python cannot resolve `from src.models import Chunk` etc.

**No attribution comments:** As of Phase 4, no source file may contain a
watermark or attribution comment of any kind. Any such comment found in an
older file must be removed when that file is next touched.

---

## 6. Models

### 6.1 Embedding Model (ingestion + query time)

- **Model:** `BAAI/bge-large-en-v1.5`
- **Location:** `/home/graphrag-automation/graphrag_engine/models/bge-large-en-v1.5/`
- **Format:** HuggingFace directory (safetensors + config + tokenizer)
- **VRAM usage:** ~1.34GB
- **Dimensions:** 1024 (NOT 768 — old nomic model was 768)
- **Library:** `sentence-transformers`, device=cuda
- **PREFIX RULES (BGE-specific):**
  - Documents (ingestion): NO prefix. Raw text only.
  - Queries (retrieval): `"Represent this sentence for searching relevant passages: "` + query text
- **DO NOT** use nomic prefixes (`search_document:`, `search_query:`) — model was upgraded

### 6.2 Entity Extraction LLM (ingestion Stage 3 only — runs on port 8080)

- **Model:** `Meta-Llama-3.1-8B-Instruct-Q8_0.gguf`
- **Location:** `/home/graphrag-automation/graphrag_engine/models/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf`
- **Format:** GGUF (self-contained, no additional files needed)
- **VRAM usage:** ~8.5GB (all 33 layers on GPU)
- **Library:** `llama-cpp-python` (compiled with GGML_CUDA=on)
- **Threading:** n_threads=8, n_threads_batch=8
- **Temperature:** 0.0 (deterministic extraction)
- **CRITICAL:** Runs as standalone HTTP API on port 8080. graph_builder.py sends
  HTTP POST requests to it. Never loaded directly in the ingestion process.

### 6.3 Reranker (query time only)

- **Model:** `BAAI/bge-reranker-v2-m3`
- **Location:** `/home/graphrag-automation/graphrag_engine/models/bge-reranker-v2-m3/`
- **Library:** sentence-transformers CrossEncoder
- **VRAM:** ~1.1GB. RELEVANCE_THRESHOLD=0.15 (below this = no-data response, no LLM call)
- **Loaded once** at server startup via shared instance. Never re-instantiated per query.

### 6.4 Query Router (query time — always local)

- **Model:** `Qwen3.6-12B-IQ-Q4_K_M.gguf`
- **Location:** `/home/graphrag-automation/graphrag_engine/models/Qwen3.6-12B-IQ-Q4_K_M.gguf`
- **VRAM:** ~7GB, n_ctx=8192, n_threads=8
- **Role:** Query analysis, intent extraction, entity recognition, expanded queries
- **Thinking mode ON** for routing — strip `<think>...</think>` blocks from output
- **Always local regardless of production mode** — routing stays on-device

### 6.5 Final Answer Generation (two modes)

**Local / testing mode (current):**

- Uses shared Qwen instance (same model as router, 6.4 above)
- /no_think prefix prepended, temperature=0.1
- Zero additional VRAM — shared instance

**Production mode (planned — not yet active):**

- **Option A:** Claude Sonnet via Anthropic API (`ANTHROPIC_API_KEY`)
  — highest quality, most expensive
- **Option B:** GPT-4o-mini via OpenAI API (`OPENAI_API_KEY`)
  — cost-effective alternative, under evaluation
- Decision pending: boss approval + cost analysis
- API key not yet provided. Both keys set to `placeholder` in .env.
- fastapi_service.py detects which key is configured and routes accordingly
- Note: Ingestion pipeline does NOT need either API key. Only fastapi_service.py uses them.

---

## 7. Environment Variables (.env — chmod 444, never overwrite via scp)

```dotenv
# --- CLOUD QUERY GENERATION (production) ---
# One of these will be used for final answer generation in production.
# Sonnet = highest quality. GPT-4o-mini = cost-effective alternative.
ANTHROPIC_API_KEY=placeholder
CLAUDE_MODEL=claude-sonnet-4-6
OPENAI_API_KEY=placeholder
OPENAI_MODEL=gpt-4o-mini

# --- LOCAL LLM (entity extraction during ingestion — runs on port 8080) ---
LLAMA_MODEL_PATH=/home/graphrag-automation/graphrag_engine/models/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf
LLAMA_N_GPU_LAYERS=-1
LLAMA_N_CTX=4096
LLAMA_N_BATCH=512
LLAMA_N_THREADS=8
LLAMA_N_THREADS_BATCH=8
LLM_API_URL=http://127.0.0.1:8080

# --- QUERY ROUTING + LOCAL GENERATION (Qwen, always on) ---
QWEN_MODEL_PATH=/home/graphrag-automation/graphrag_engine/models/Qwen3.6-12B-IQ-Q4_K_M.gguf
QWEN_N_GPU_LAYERS=-1
QWEN_N_CTX=8192
QWEN_N_BATCH=512
QWEN_N_THREADS=8
QWEN_N_THREADS_BATCH=8

# --- RERANKER ---
RERANKER_MODEL_PATH=/home/graphrag-automation/graphrag_engine/models/bge-reranker-v2-m3
RELEVANCE_THRESHOLD=0.15

# --- EMBEDDING ---
EMBED_MODEL_PATH=/home/graphrag-automation/graphrag_engine/models/bge-large-en-v1.5
EMBED_DEVICE=cuda

# --- PATHS ---
DATA_DIR=data
INGESTION_DIR=ingestion_mouth
CHROMA_PATH=data/chroma_db
CHROMA_COLLECTION=legal_chunks
BM25_INDEX_PATH=data/bm25_index/bm25.pkl
GRAPH_PATH=data/knowledge_graph.json
INGESTION_LOG_PATH=data/ingestion_log.json
HDD_BASE_PATH=/opt/graphrag/data/ingestion_pool

# --- HUGGINGFACE (suppress all network calls) ---
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
HF_HUB_DISABLE_SYMLINKS_WARNING=1

# --- TESSERACT ---
TESSERACT_LANG=eng
TESSDATA_PREFIX=/usr/share/tessdata

# --- OTHER ---
SP_ENABLED=false
MAX_SESSIONS=100
MAX_TURNS_PER_SESSION=50
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

**Common .env mistakes that caused failures:**

- `LLAMA_MODEL_PATH=LLAMA_MODEL_PATH=/mnt/...` — duplicated key prefix. Fix: remove prefix.
- Keeping old model name `Meta-Llama-3-8B-Instruct.Q4_K_M.gguf` after upgrade to Q8_0.

---

## 8. Ingestion Pipeline (Current Architecture)

```
batch_coordinator.py (BATCH_SIZE=1, subprocess isolation per file)
  │
  ├── Verify port 8080 is running (LLM inference server)
  ├── For each PDF in staging/:
  │     LD_PRELOAD=jemalloc subprocess.Popen([venv/python, run_ingestion.py, --source staging])
  │     ← new OS process per file — RAM fully wiped between every PDF
  │     ├── exit code 0:  shutil.move → archive/
  │     └── non-zero exit: log traceback → quarantine/*.error.log, shutil.move → quarantine/
  └── Loop continues to next file regardless of failures

run_ingestion.py (per-file subprocess — inside fresh OS process)
  ├── Stage 1: parser.py     (strategy="fast", MAX_CHUNK_TOKENS=700)
  ├── Stage 2: vector_embed.py (BGE-large, device=cuda, del model + empty_cache after)
  ├── Stage 3: graph_builder.py (HTTP POST to http://127.0.0.1:8080 — NO local llama_cpp)
  └── Stage 4: keyword_index.py (BM25 full-corpus rebuild)

inference_server.py (always-on separate process on port 8080 during ingestion)
  └── llama_cpp.server wrapping Llama 3.1 8B Q8_0 — handles entity extraction calls
```

**Required environment before launching anything ingestion-related:**

```bash
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
source venv/bin/activate
```

---

## 9. Query Pipeline

```
Auditor Query → FastAPI port 8000
  → Query Router (Qwen shared instance, thinking ON, <think> blocks stripped)
  → 3-Path Retrieval (Vector + Graph BFS + BM25)
  → RRF Fusion (k=60)
  → Cross-Encoder Reranking (BGE reranker, sigmoid 0-1)
  → Relevance Gate (threshold 0.15 — below = no-data response, no LLM call)
  → Final Generation:
      Local/testing:  Qwen shared instance (/no_think prefix)
      Production:     Claude Sonnet (Anthropic) OR GPT-4o-mini (OpenAI)
  → Response: answer + inline [chunk_id] citations + sources footer
```

**VRAM sharing at query time (critical rules):**

- QueryRouter uses shared qwen_llm — no new Llama() instantiation
- Reranker uses shared instance via search_engine.set_reranker()
- A second Llama() anywhere in query path = immediate VRAM segfault

---

## 10. Evaluation Baseline

- **Total:** 100/100 [SUCCESS] (confirmed)
- **Average query time:** ~20 seconds per query
- **Known acceptable fallbacks** (always return knowledge-base message — not failures):
  TEST_049, TEST_059, TEST_082, TEST_086, TEST_092, TEST_095, TEST_099
- **Regression threshold:** below 95/100 = do not deploy the triggering change

---

## 11. Complete Change Log

### Stage 1: Initial build (Antigravity + Gemini agent)

- Built all source files from GRAPHRAG_SKILL.md specification
- Modules: models.py, tracker.py, parser.py, vector_embed.py, graph_builder.py,
  keyword_index.py, hybrid_search.py, fastapi_service.py, inference_server.py,
  run_ingestion.py, deploy_arch.sh, requirements.txt

### Stage 2: Code review fixes (pre-deployment)

- hybrid_search.py: embed_query() was calling inline encode() instead of importing
  from vector_embed.py. Fixed — BGE prefix must be applied once in one place.

### Stage 3: Arch Linux deployment issues

- Python 3.14 on server: pyenv installed, Python 3.11.9 set globally
- llama-cpp-python CUDA build: CMAKE_ARGS="-DGGML_CUDA=on" (LLAMA_CUDA is deprecated)
- PATH issue: nvcc not in PATH until `source /etc/profile` after pacman install
- Missing **init**.py: all 5 package directories were missing them
- einops missing: added `pip install einops`, added to requirements.txt

### Stage 4: First ingestion run (6 test files, non-CA documents)

- strategy="hi_res" caused 42-minute timeout — fixed to strategy="fast"
- LLAMA_MODEL_PATH duplicate key in .env — fixed
- First successful full ingestion: 2579 chunks, BGE on GPU, 33/33 Llama layers on GPU

### Stage 5: Model upgrades

- nomic-embed → bge-large-en-v1.5 (768-dim → 1024-dim, better retrieval)
- Llama-3-8B Q4_K_M → Llama-3.1-8B Q8_0 (better JSON extraction reliability)
- ChromaDB dimension mismatch after upgrade: deleted chroma_db/ and rebuilt
- Updated BGE prefix rules throughout codebase

### Stage 6: Performance optimisations

- CPU governor set to performance (was powersave — capped at 14%)
- n_threads=8, n_threads_batch=8 added to Llama() constructor
- MAX_CHUNK_TOKENS increased 450 → 700 (legal clauses need larger chunks)
- HF_HUB_OFFLINE=1 to suppress network warnings
- Preflight check added to run_ingestion.py

### Stage 7: Query pipeline built

- Added: hybrid_search.py (3-path + RRF), query_router.py (Qwen routing),
  reranker.py (BGE cross-encoder), conversation_manager.py, fastapi_service.py
- Fixed double-instantiation bugs: QueryRouter and Reranker both creating second
  instances → VRAM overflow → segfault. Fixed via dependency injection.
- graph_io.py created to separate save/load from llama_cpp dependency chain
- load_dotenv() added to top of fastapi_service.py (was causing KeyError on env vars)

### Stage 8: AS standard documents ingested — eval completed

- 29 unique AS standard PDFs ingested (AS 1 through AS 29)
- Knowledge base: 2224 chunks, 6115 graph nodes, 4246 edges
- Full 100-question evaluation: 100/100 [SUCCESS]
- Average query time: ~20 seconds

### Stage 9: VRAM crash investigation and architecture fix (2026-06-18)

- Exit Code -11 (SIGSEGV): PyTorch (BGE) and llama.cpp colliding in VRAM in same process
  Fix: decoupled Llama to standalone HTTP API on port 8080. graph_builder.py now uses
  HTTP POST. PyTorch and llama.cpp are now in separate OS processes — no VRAM collision.
- Exit Code -6 (SIGABRT) double-free: ChromaDB/PyTorch memory leak across sequential docs
  Fix: BATCH_SIZE=1 strict process isolation. Each file runs in its own subprocess.
  OS wipes RAM completely between every PDF.
- Memory fragmentation freezing Linux: glibc malloc fails during 50+ hour runs
  Fix: LD_PRELOAD=/usr/lib/libjemalloc.so + PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
- Port 8080 ghost process: `pkill -9 -f llama_cpp.server`
- Claude Code CWD bug: was C:\Users\Joel Anthony\ instead of E:\ project root
  Fix: manually copy files from C: to E:, sync to server

### Stage 10: Frontend and monitoring built (2026-06-18)

- gui/main.py: PyQt6 main window, three-pane layout (BUILT)
- gui/styles.qss: Catppuccin Mocha dark theme (BUILT)
- gui/api_client.py: QThread workers — in progress
- gui/ingestion_monitor.py: Ingestion control panel — in progress
- telemetry_dashboard.py: Live ingestion monitoring with ETA and token rate
- logs/ingestion_metrics.csv: Telemetry log appended during ingestion
- mock_api.py: Local Windows dummy server for GUI testing without GPU

### Stage 11: Phase 2 GUI — Knowledge Management and Inline Audit Trail (2026-06-20)

- prune_document.py created: standalone 4-step pruning script (ChromaDB delete →
  BM25 rebuild → knowledge_graph.json node/edge severing → file move to archive/)
- gui/tabs/knowledge_tab.py: archive document table with per-row Prune action,
  QFileSystemWatcher-driven auto-refresh
- gui/widgets/accordion_message.py: AccordionAIMessage replaces plain AI text bubble,
  collapsible "View Source Evidence" panel showing raw retrieved chunks
- gui/workers/pruning_worker.py: QThread wrapping prune_document.py subprocess,
  streams stdout, reports progress via signal
- StateManager extended with a pruning section; mutual exclusion now covers three
  states (ingesting / querying / pruning) rather than two
- Bug found: ingestion start button only checked is_ingesting(), not pruning or
  query state — fixed by adding both checks before allowing ingestion to start
- Bug found: StateManager.read() was being called synchronously inside GUI button
  click handlers in query_tab.py and knowledge_tab.py — flagged for Phase 3 fix
  (async state reads via cached telemetry signal, not direct disk read)

### Stage 12: Phase 3 — Zombie Lock Fix, ServerManager, Quarantine, UI Patches (2026-06-23 to 06-29)

- **Critical bug:** GUI permanently locked into "ingesting" state after backend crash,
  even with 0% CPU/GPU telemetry. Root cause: static boolean is_ingesting() flag never
  cleared on process death. Fix: replaced with psutil.pid_exists(pid) heartbeat polled
  every 1000ms inside TelemetryWorker. Dead PID triggers automatic state reset to idle —
  zombie locks now self-heal within one telemetry tick, no manual intervention required.
- gui/services/server_manager.py created: ServerManager class checks port 8000 via raw
  TCP socket connect, kills any ghost process (sudo fuser -k 8000/tcp), and launches
  uvicorn as a detached subprocess (start_new_session=True) so it survives GUI restarts.
  QueryTab disables the Submit button until ServerManager + HealthCheckWorker confirm
  the port is live.
- run_ingestion.py: added SKIP_EXTENSIONS set and known corrupt-PDF error signatures
  ("No /Root object!", "Unsupported extension", "PdfReadError", "EOF marker not found").
  Any file matching either condition is shutil.move()'d straight to quarantine/ instead
  of being left in staging/ to be rescanned on every subsequent boot.
- UI bug patch batch (all confirmed and fixed):
  - VRAM telemetry divided bytes by 1,000,000,000 (decimal) instead of 1024**3 (binary),
    showing 13GB instead of the correct ~11.6 GiB on a 12GB card. Fixed.
  - IngestionTab directory buttons were mislabelled/misrouted ("Open quarantine" opened
    archive/, "View error logs" opened quarantine/). Relabelled to "Open Archive" and
    "Open Quarantine" with corrected xdg-open targets.
  - Pause button showed "Stopping..." instead of "Pausing..." — corrected.
  - QComboBox in QueryTab had no visible drop-down arrow — QComboBox::drop-down and
    ::down-arrow sub-controls were missing from theme.qss entirely. Added.
  - QueryTab model selector had no "Models" label above it. Added QLabel("Models").
  - Ingestion telemetry labels (Queue/Session/Batch/Current file) were static and never
    updated. Wired via a [TELEMETRY] structured log-line protocol: batch_coordinator.py
    emits key=value lines at the start of every stage; IngestionTab.on_log_line() parses
    them and updates the corresponding QLabel widgets live.
- All five Phase 3 micro-phases passed Tester static analysis and Security audit.
  Pipeline closed 2026-06-29.

### Stage 13: Phase 4 — GraphRAG Editorial Design System Qt Translation (2026-06-30, in progress)

- docs/DESIGN_SYSTEM.md adopted as canonical brand specification, written originally
  in web/Tailwind terms and translated into native PyQt6 constructs.
- SKILL_PHASE4_UI.md created: exact QFontDatabase code for loading Cormorant Garamond
  (display), DM Sans (UI), DM Mono (monospace) from gui/assets/fonts/; full
  ThemeLoader.TOKENS replacement mapping every GraphRAG brand colour, the 8-point spacing
  grid, and the six-tier radius system; complete theme.qss rewrite covering every
  widget class used across Phases 1-3 (buttons, inputs, cards, tabs, tables, combobox,
  scrollbars, splitter, tooltip, accordion, chat bubbles).
- Catppuccin Mocha theme retired in full — no hex values from that palette may remain.
- Watermark/attribution policy introduced: no source file may contain any
  "Engineered by/for" style comment from this point forward; existing instances are
  removed as files are touched.
- This stage absorbs and closes out CLAUDE_UPDATES_2026-06-20.md and
  CLAUDE_UPDATES_2026-06-29.md — both are now historical, their content fully merged
  into this change log and into CLAUDE.md's Current Status / Bug History sections.

---

## 12. System Behaviour — What Normal Looks Like

### Stage 1: Parsing

- Prints `[N/total] Parsing: filename.pdf` for each file
- CPU: 49-75% (Xeon W-2125, mostly single-threaded unstructured work)
- GPU: 0% (not used for parsing)
- Duration: ~30-60 seconds per typical PDF with strategy="fast"

### Stage 2: Vector Embedding

- Prints `Embedding model loaded on GPU: NVIDIA GeForce RTX 3060`
- Prints `VRAM used: ~1.34 GB`
- GPU: 60-80% utilisation during batch encoding
- Duration: ~8-15 seconds per 1000 chunks at batch_size=64

### Stage 3: Graph Construction (via port 8080)

- graph_builder.py sends HTTP POST requests to 127.0.0.1:8080
- Llama process (port 8080) shows `llm_load_tensors: offloaded 33/33 layers to GPU`
- VRAM on port 8080 process: ~8.5GB
- GPU: 90-96% utilisation during inference
- `CUDA Graph id XXXX reused` messages are normal — performance optimisation
- Speed: ~1.5-7 seconds per chunk depending on content density
- Duration: 1-2 hours for 1000+ chunks (Xeon bottleneck during JSON parsing)

### Stage 4: BM25

- Near-instant: `BM25 index built: N documents indexed`
- Pure Python, no GPU

---

## 13. Commands Reference

### Start LLM inference server (port 8080 — before ingestion)

```bash
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
source venv/bin/activate
python -m llama_cpp.server \
  --model /home/graphrag-automation/graphrag_engine/models/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf \
  --host 127.0.0.1 --port 8080 --n_gpu_layers -1 --n_threads 8
```

### Start batch ingestion

```bash
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
source venv/bin/activate
tmux new-session -s batch
python batch_coordinator.py
# Detach: Ctrl+B, D
```

### Start query API (port 8000 — after ingestion, port 8080 must be stopped)

```bash
fuser -k 8080/tcp && pkill -9 -f llama_cpp.server
source venv/bin/activate
uvicorn src.api.fastapi_service:app --host 0.0.0.0 --port 8000
```

### Monitor ingestion telemetry

```bash
source venv/bin/activate
python telemetry_dashboard.py
```

### Run eval suite (query server must be running)

```bash
source venv/bin/activate
python run_eval.py
```

### Launch PyQt6 GUI (GNOME terminal on Arch server)

```bash
export QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"
source venv/bin/activate
python gui/main.py
```

### GPU check

```bash
watch -n 2 nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv
```

### Kill port 8080 if stuck

```bash
pkill -9 -f llama_cpp.server
fuser -k 8080/tcp
```

### Verify system state

```bash
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq  # should be: performance
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
ls -lh models/
ls /usr/lib/libjemalloc.so  # must exist
grep "MODEL_PATH\|API_KEY\|LLM_API_URL" .env
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## 14. DO NOT List (Hard Rules)

1. DO NOT use nomic prefixes (`search_document:`, `search_query:`) — model is BGE-large
2. DO NOT use strategy="hi_res" for bulk ingestion — use strategy="fast"
3. DO NOT load llama_cpp directly in the ingestion process — use HTTP to port 8080
4. DO NOT run port 8000 and port 8080 simultaneously — VRAM overflow
5. DO NOT use system Python 3.14 — always pyenv 3.11.9 via venv
6. DO NOT install llama-cpp-python without CMAKE_ARGS="-DGGML_CUDA=on"
7. DO NOT use nx.DiGraph or nx.Graph — must be nx.MultiDiGraph
8. DO NOT lowercase BM25 corpus tokens — legal identifiers must match exactly
9. DO NOT run ingestion without LD_PRELOAD=jemalloc set
10. DO NOT use LLAMA_CUDA flag — deprecated, use GGML_CUDA
11. DO NOT forget **init**.py in every src/ subdirectory
12. DO NOT rebuild BM25 from only new chunks — rebuild from full ChromaDB corpus
13. DO NOT confuse dev machine (RTX 5050 8GB) with server (RTX 3060 12GB)
14. DO NOT scp .env — it is chmod 444 on the server
15. DO NOT bind port 8080 to 0.0.0.0 — localhost only (127.0.0.1)
16. DO NOT suggest ExLlamaV2, FlashAttention-2, or multiprocessing GIL refactors
17. DO NOT run Claude Code with CWD set to C:\Users\ — must be E:\ project root
18. DO NOT import llama_cpp anywhere in graph_io.py, hybrid_search.py, or fastapi_service.py
19. DO NOT use a static boolean flag (e.g. is_ingesting = True) to track backend process
    liveness — always use psutil.pid_exists(pid), checked every 1000ms in TelemetryWorker
20. DO NOT use shell=True in any subprocess call, including ServerManager's port-kill
    and uvicorn launch — always pass arguments as a list
21. DO NOT hardcode hex colour values, pixel margins, or font names in any .py file —
    all visual values live in ThemeLoader.TOKENS and gui/styles/theme.qss only
22. DO NOT add watermark or attribution comments to any source file — remove any found
    in existing files when touched (see Stage 13, Phase 4)
23. DO NOT divide GPU memory bytes by 1,000,000,000 for VRAM display — use 1024**3 (GiB)

---

## 15. Outstanding Work and Next Steps

In priority order:

1. Phase 4: Source and bundle 8 required .ttf font files into gui/assets/fonts/
   (Cormorant Garamond Regular/Medium/SemiBold, DM Sans Regular/Medium/Bold,
   DM Mono Regular/Medium)
2. Phase 4: Implement FontLoader class and updated ThemeLoader.TOKENS per
   SKILL_PHASE4_UI.md — full Catppuccin Mocha removal
3. Phase 4: Rewrite gui/styles/theme.qss body using GraphRAG brand tokens
4. Phase 4: Sweep every source file for attribution comments and remove them
5. Phase 4: Tester confirms zero Catppuccin hex values remain; Security confirms
   zero attribution strings remain anywhere in gui/ or src/
6. Monitor telemetry dashboard until 500+ file pool ingestion completes (est. Sunday)
7. Integration testing: PyQt6 GUI end-to-end with live query server on port 8000
8. Verify PyVis physics-based graph rendering in QWebEngineView
9. Run full eval suite (run_eval.py) to confirm 100/100 baseline holds
10. Decide on production generation model: Sonnet vs GPT-4o-mini (cost analysis)
11. Get API key from boss → replace placeholder in .env → test cloud generation
12. Implement old SharePoint chunk reuse once export format is confirmed
13. Hook into company website/server (production deployment — future phase)

---

*GraphRAG Engine Master Context — maintained by GraphRAG Platform Innovation & Technology Team*
*Last updated: June 30, 2026*
