# GraphRAG Prototype System — Comprehensive Architecture & Codebase Map

> **Legal & Regulatory Compliance Intelligence Engine — Legal Discovery & Compliance Engine**  
> *Authoritative Codebase Audit, Directory Structure, and Architectural Documentation*

---

## 1. Executive Summary

The **GraphRAG Engine** is an enterprise legal research and statutory compliance assistant purpose-built for **GraphRAG Platform** (a premier Indian Chartered Accountancy and Audit firm). The system ingests vast corpora of complex statutory documents—including the **Goods and Services Tax (GST) Acts**, **Income Tax Act**, **Accounting Standards (AS / Ind AS / ASLB)**, **ICAI Circulars & Guidance Notes**, **Foreign Exchange Management Act (FEMA)**, and corporate audit annexures—and synthesizes factual, auditable, and citation-anchored compliance answers.

To eliminate hallucinations while preserving multi-step legal reasoning (e.g., how an exemption in Section 17(5) overrides general input tax credit rules in Section 16), the engine implements a **3-Path Hybrid GraphRAG architecture**:
1. **Dense Semantic Vector Retrieval** (`BAAI/bge-large-en-v1.5` over ChromaDB)
2. **Knowledge Graph Subgraph Traversal** (Breadth-First Search over a `NetworkX MultiDiGraph` storing statutory entities and directed legal relations)
3. **Sparse Lexical Search** (Exact case-preserved `BM25Okapi` indexing for section numbers, forms, and statutory clauses)
4. **Reciprocal Rank Fusion (RRF)** combined with a **Cross-Encoder Reranker** (`BAAI/bge-reranker-v2-m3`) and a strict **Relevance Gate** ($0.15$ threshold) before context synthesis.

---

## 2. Core Architectural Pillars

### 2.1 The Two-Machine Distributed Paradigm
The project operates across two distinct physical machines with strict operational separation:

```
┌─────────────────────────────────────────────────────────┐
│        MACHINE 1: Windows Dev Machine (Workstation)      │
│  • OS: Windows 11 | CPU: AMD Ryzen 7 250 AI             │
│  • GPU: NVIDIA RTX 5050 (8GB VRAM) | RAM: 16GB          │
│  • Role: Pure code editing in Antigravity / VS Code     │
│  • Rule: NEVER run ingestion, servers, or pip here.     │
└───────────────────────────┬─────────────────────────────┘
                            │  Transfer via scp / git
                            ▼
┌─────────────────────────────────────────────────────────┐
│         MACHINE 2: Arch Linux Server (Production)        │
│  • OS: Arch Linux | CPU: Intel Xeon W-2125 (4c/8t)      │
│  • GPU: NVIDIA RTX 3060 (12GB VRAM, CUDA 13.3)         │
│  • RAM: 32GB DDR4 | Storage: 476GB SSD + 932GB HDD      │
│  • Python: pyenv 3.11.9 (System Python 3.14 forbidden)  │
│  • Role: ALL runtime computation, GUI execution, servers│
└─────────────────────────────────────────────────────────┘
```

---

### 2.2 The Two-Port Mutual Exclusion Architecture
The Arch Linux production environment features a 12GB VRAM ceiling (NVIDIA RTX 3060). Running LLM extraction concurrently with the multi-model query stack would cause catastrophic CUDA Out-Of-Memory (OOM) / `SIGSEGV` aborts. Hence, the system enforces **hard temporal mutual exclusion**:

```
           12GB VRAM Hardware Budget Allocation
           
  [QUERY TIME — Port 8000]                [INGESTION TIME — Port 8080]
  ┌─────────────────────────┐             ┌─────────────────────────┐
  │ BGE Embed:      1.34 GB │             │ Llama 3.1 8B Q8: 8.50 GB│
  │ BGE Reranker:   1.10 GB │             │ PyTorch Buffers: 1.50 GB│
  │ Qwen 12B Q4_K_M:7.00 GB │             │ OS / Overhead:   1.00 GB│
  │ KV Cache/Buffers:1.00 GB│             ├─────────────────────────┤
  ├─────────────────────────┤             │ Total:         ~11.00 GB│
  │ Total:         10.44 GB │             │ Headroom:        1.00 GB│
  │ Headroom:       1.56 GB │             └─────────────────────────┘
  └─────────────────────────┘
```

* **Port 8000 — Query API Server (`src/api/fastapi_service.py`):** Loads BGE-large-en, BGE Reranker, and Qwen3.6-12B simultaneously. Started via Uvicorn. Exposes `/query`, `/health`, and session management.
* **Port 8080 — Standalone LLM Server (`src/api/inference_server.py`):** Loads Meta-Llama-3.1-8B-Instruct-Q8_0 for entity/relation extraction during ingestion Stage 3. Decoupled into a separate OS process so PyTorch CUDA tensors and `llama.cpp` never share address space.
* **Port Kill Rule:** Before starting either server, `fuser -k 8000/tcp` and `fuser -k 8080/tcp` run to destroy ghost sockets and free CUDA memory.

---

### 2.3 End-to-End Ingestion Pipeline (Subprocess-Isolated)

Ingestion transforms raw statutory PDFs and documents into 3 coordinated databases using an isolated batch workflow:

```
[Unprocessed Pool (HDD)] ──> [Staging Area (HDD)]
                                      │
                                      ▼
                        batch_coordinator.py (Subprocess Wrapper)
                                      │
                 ┌────────────────────┴────────────────────┐
                 ▼                                         ▼
         (Exit code 0)                             (Non-zero Exit)
       shutil.move to                            shutil.move to
       archive/ (HDD)                            quarantine/ (HDD)
```

Each document executes inside a dedicated `run_ingestion.py` subprocess, guaranteeing that the OS fully recovers memory between files, precluding CUDA/glibc memory leaks:

1. **Stage 1 — Layout-Aware Parsing (`src/ingestion/parser.py`):**
   * Employs `unstructured` (`strategy="fast"`) for PDF, DOCX, HTML, TXT, and `openpyxl`/`csv` for spreadsheets.
   * Extracts layout elements (`Title`, `NarrativeText`, `Table`, `ListItem`). Tracks closest preceding `Title` as `section_header`.
   * Chunks with `tiktoken` (`MAX_CHUNK_TOKENS=700`). Generates unique deterministic 16-character IDs: `hashlib.sha256(f"{source_path}:{offset}".encode()).hexdigest()[:16]`.
   * If parsing fails or yields corrupt text, automatically routes the file to `quarantine/`.
2. **Stage 2 — Dense Vector Embedding (`src/extraction/vector_embed.py`):**
   * Encodes chunks using `BAAI/bge-large-en-v1.5` on CUDA (1024 dimensions).
   * Upserts into persistent ChromaDB collection (`legal_chunks`) with full metadata (`source_path`, `page_number`, `section_header`, `element_type`, `offset`).
   * Explicitly frees VRAM via `del model` and `torch.cuda.empty_cache()` if invoked in isolated stages.
3. **Stage 3 — Knowledge Graph Construction (`src/extraction/graph_builder.py`):**
   * Dispatches chunks over HTTP to `http://127.0.0.1:8080` where Llama-3.1 8B extracts entities and relations following strict tax law ontology.
   * Entities mapped to `VALID_NODE_TYPES`: `Act`, `Section`, `SubSection`, `Clause`, `Rule`, `Notification`, `Circular`, `Definition`, `Exception`, `Form`, `Penalty`, `PenalCode`.
   * Relationships mapped to `VALID_EDGE_TYPES`: `AMENDED_BY`, `EXCEPTION_TO`, `DEFINITION_OF`, `APPLIES_TO`, `REFERS_TO`, `SUBJECT_TO`, `OVERRIDES`, `EXPLAINED_BY`, `PENALTY_UNDER`, `NOTIFIED_UNDER`, `CROSS_REFERENCED_BY`.
   * Merges extracted subgraphs into the global `NetworkX MultiDiGraph` and writes atomically via `src/extraction/graph_io.py`.
4. **Stage 4 — BM25 Sparse Index Rebuild (`src/extraction/keyword_index.py`):**
   * Reads tokens across all chunks without lowercasing or stopword removal (crucial for exact matches on statutory tokens like "Section 17(5)", "Form GSTR-3B", "AS 10").
   * Serializes `BM25Okapi` index to `data/bm25_index/bm25.pkl`.

---

### 2.4 End-to-End Query & Retrieval Pipeline

When an auditor submits a compliance question, the query executes through an auditable multi-hop pipeline:

```
Auditor Query 
   │
   ▼
[1. Query Router] (Local Qwen3.6-12B, Thinking Mode ON)
   │  Extracts: legal intent, entities, graph seeds, 2-3 expanded query formulations
   │
   ▼
[2. Tri-Hybrid Retrieval]
   ├── Path 1: Vector Search ──> BGE-large-en-v1.5 (ChromaDB cosine similarity)
   ├── Path 2: Graph BFS ──────> MultiDiGraph 2-hop ego-graph expansion from seed nodes
   └── Path 3: Keyword Search ─> BM25Okapi exact case-preserved token scoring
   │
   ▼
[3. Reciprocal Rank Fusion (RRF)]
   │  Computes RRF score: score(d) = Σ [ 1 / (k + rank_i + 1) ] with k = 60
   │
   ▼
[4. Cross-Encoder Reranker] (BAAI/bge-reranker-v2-m3)
   │  Scores (query, passage) pairs, normalizes via sigmoid (0.0 to 1.0)
   │
   ▼
[5. Relevance Gate]
   │  If all chunk scores < 0.15 ──> Halts, returns "Insufficient Context" (prevents hallucinations)
   │
   ▼
[6. Final Compliance Generation]
   ├── Testing Mode:    Local Qwen3.6-12B (/no_think prefix, zero commentary)
   └── Production Mode: Claude 3.5 Sonnet / GPT-4o-mini via API
   │
   ▼
Final Output: Factual compliance answer + Inline hexadecimal [chunk_id] citations + Source audit list
```

---

### 2.5 Desktop GUI Client Architecture (PyQt6 Native GNOME)

The frontend is a dedicated PyQt6 desktop application running natively on the Arch Linux workstation, styled using the custom **GraphRAG Editorial Design System**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      GraphRAG Platform GraphRAG Desktop Client                  │
├───────────────────┬──────────────────────────────────┬──────────────────────┤
│  Tab 1: Ingestion │        Tab 2: Legal Query        │  Tab 3: Knowledge    │
│  Controls & Logs  │    Chat & PyVis Visualizer       │  Archive & Pruning   │
└───────────────────┴──────────────────────────────────┴──────────────────────┘
```

* **Main Thread 144Hz Smoothness:** No blocking operations in the Qt event loop. Network calls, filesystem checks, and model inferences live strictly inside dedicated `QThread` workers (`QueryWorker`, `TelemetryWorker`, `IngestionWorker`, `PruningWorker`).
* **Atomic JSON IPC (`gui/state/state_manager.py`):** GUI and background processes communicate through `data/gui_state.json`. All writes use the `NamedTemporaryFile` + `os.replace` atomic replacement pattern.
* **Zombie Lock Healing:** Uses `psutil.pid_exists(pid)` to check process liveness every 1000ms. If an ingestion or pruning process dies abruptly, the UI automatically clears dead locks within 1 second.
* **Dynamic PyVis Network (`gui/widgets/graph_view.py`):** Embeds an interactive HTML force-directed graph within `QWebEngineView`, communicating bidirectionally via `QWebChannel` to highlight active citation nodes.
* **Accordion Evidence Bubble (`gui/widgets/accordion_message.py`):** Displays audit trails with collapsible source passage cards showing verbatim extracts and relevance scores.
* **GraphRAG Editorial Design System (`gui/styles/theme.qss`):** Replaces default styles with warm neutral tones (`#faf8f5` light, `#191919` dark, `#9a3324` accent) and loaded typography (`Cormorant Garamond` display, `DM Sans` UI, `DM Mono` code).

---

## 3. Complete Workspace File & Folder Directory Structure

```

├── AGENTS.md                          # Role definitions, agent rules & coordination protocol
├── CHANGES_SUMMARY.md                 # Global append-only chronological change history
├── CLAUDE.md                          # Authoritative project manual, hardware constraints & bug history
├── CLAUDE_UPDATES_2026-06-20.md       # Phase 2 additions update proposal log (archived)
├── CLAUDE_UPDATES_2026-06-29.md       # Phase 3 additions update proposal log (archived)
├── CLAUDE_UPDATES_2026-06-30_phase4.md# Phase 4 GraphRAG design system update proposal log
├── CLAUDE_UPDATES_2026-07-13.md       # Post-Phase 4 prompt hardening and Phase 5 roadmap
├── FRONTEND.md                        # PyQt6 desktop client architectural specification
├── MASTER_CONTEXT.md                  # Comprehensive master history superseding past docs
├── ROUTINES.md                        # Step-by-step operating procedures for all server tasks
├── UNIFIED_MEMORY.md                  # Agent coordination blackboard and task state machine
├── docs/DESIGN_SYSTEM.md             # Canonical GraphRAG Platform brand design system
├── GraphRAG.md                        # [THIS FILE] Complete architecture & codebase catalog
│
├── skills/                            # Engineering doctrine & phase specification skills
│   ├── SKILL.md                       # Core engineering laws, VRAM rules & non-negotiable constraints
│   ├── SKILL_GUI.md                   # Phase 1 PyQt6 desktop application specification
│   ├── SKILL_PHASE2.md                # Phase 2 blueprint: pruning, accordion bubbles, QSplitter
│   └── SKILL_PHASE4_UI.md             # Phase 4 design system Qt translation & font loading spec
│
└── graphrag_engine/                   # Core Python engine and application root
    ├── .env                           # Server environment variables & API keys (chmod 444 on server)
    ├── .env.example                   # Template environment configuration file
    ├── .gitignore                     # Git ignore file for Python, venv, and data caches
    ├── CHANGES_SUMMARY.md             # Engine-level changes summary log
    ├── UNIFIED_MEMORY.md              # Engine-level blackboard memory file
    ├── daily_cycle.sh                 # Nightly bash cycle (orchestrates ingestion or validation)
    ├── graphrag-api.service           # Systemd unit file for FastAPI port 8000 daemon
    ├── local_stability_report.log     # Test output log from isolated 10-query stability run
    ├── prune_document.py              # Standalone atomic 4-step document pruning script
    ├── query_engine.py                # Standalone CLI hybrid retrieval & synthesis script
    ├── requirements.txt               # Python package dependencies
    ├── run_ingestion.py               # Ingestion CLI & pipeline runner (stages 1-4)
    ├── run_local_stability_test.py    # Local mock test harness for query_engine.py
    ├── validate_system.py             # System health verification daemon for ChromaDB & Graph
    │
    ├── data/                          # Persistent database layer (SSD-backed)
    │   ├── bm25_index/                # Serialized BM25 Okapi sparse index (bm25.pkl)
    │   ├── chroma_db/                 # Persistent ChromaDB vector database (1024-dim BGE)
    │   └── telemetry.db               # SQLite database for hardware & ingestion telemetry
    │
    ├── gui/                           # Native PyQt6 desktop control client
    │   ├── __init__.py                # Package initialization
    │   ├── api_client.py              # HTTP client workers (HealthCheckWorker, QueryWorker)
    │   ├── main.py                    # Application entry point, FontLoader & ThemeLoader
    │   ├── styles.qss                 # Legacy Catppuccin Mocha stylesheet
    │   ├── assets/
    │   │   └── fonts/                 # Directory for Cormorant Garamond, DM Sans, DM Mono TTFs
    │   ├── services/
    │   │   ├── __init__.py            # Package initialization
    │   │   └── server_manager.py      # Uvicorn lifecycle daemon & port conflict terminator
    │   ├── state/
    │   │   ├── __init__.py            # Package initialization
    │   │   └── state_manager.py       # Atomic JSON IPC manager (data/gui_state.json)
    │   ├── styles/
    │   │   └── theme.qss              # Master GraphRAG Editorial Design System QSS stylesheet
    │   ├── tabs/
    │   │   ├── __init__.py            # Package initialization
    │   │   ├── ingestion_tab.py       # Tab 1: Ingestion controls, telemetry gauges & live logs
    │   │   ├── knowledge_tab.py       # Tab 3: Archive document browser & atomic prune actions
    │   │   └── query_tab.py           # Tab 2: Chat panel, model selector & PyVis graph view
    │   ├── widgets/
    │   │   ├── __init__.py            # Package initialization
    │   │   ├── accordion_message.py   # Collapsible AI message bubble with citation evidence
    │   │   ├── graph_view.py          # QWebEngineView hosting interactive PyVis physics graph
    │   │   ├── mutual_exclusion_dialog.py # Context-aware VRAM conflict modal dialog
    │   │   └── spell_edit.py          # Custom QTextEdit with live spellcheck & suggestion menu
    │   └── workers/
    │       ├── __init__.py            # Package initialization
    │       ├── ingestion_worker.py    # QThread running batch_coordinator.py subprocess
    │       ├── pruning_worker.py      # QThread running prune_document.py subprocess
    │       ├── query_worker.py        # QThread sending HTTP POST queries to port 8000
    │       └── telemetry_worker.py    # QThread polling NVML GPU & psutil CPU stats every 1000ms
    │
    ├── infrastructure/                # Deployment and container orchestration
    │   ├── Dockerfile                 # NVIDIA CUDA 12.4 Ubuntu container build recipe
    │   ├── docker-compose.yml         # Container runtime with GPU device reservation
    │   ├── deploy_arch.sh             # Arch Linux server automated bootstrapping script
    │   ├── patch_llama_cpp.sh         # Helper script rebuilding llama-cpp-python with CUDA
    │   └── setup.sh                   # Python virtualenv and BGE model downloader script
    │
    ├── ingestion_data/                # Cloud synchronization utilities
    │   └── sync_sharepoint.py         # SharePoint document sync automation placeholder
    │
    ├── ingestion_mouth/               # Staging mouth & batch orchestration
    │   └── batch_coordinator.py       # Process coordinator with automatic error quarantine
    │
    ├── models/                        # Local model weights directory (SSD-backed)
    │   └── Qwen_model_snippet.py      # Reference loading snippet for Qwen GGUF model
    │
    ├── query_eso/                     # Benchmark evaluation test suites
    │   ├── graphrag_evaluator.py      # In-memory evaluation harness assessing accuracy
    │   ├── graphrag_test_suite_vol_1.json  # Multi-hop test queries (Vol 1: 25 questions)
    │   ├── graphrag_test_suite_vol_2.json  # Multi-hop test queries (Vol 2: 25 questions)
    │   ├── graphrag_test_suite_vol_3.json  # Multi-hop test queries (Vol 3: 25 questions)
    │   ├── graphrag_test_suite_vol_4.json  # Multi-hop test queries (Vol 4: 25 questions)
    │   ├── graphrag_test_suite_vol_5.json  # Multi-hop test queries (Vol 5: 25 questions)
    │   ├── graphrag_test_suite_vol_6.json  # Multi-hop test queries (Vol 6: 25 questions)
    │   ├── graphrag_test_suite_vol_7.json  # Multi-hop test queries (Vol 7: 25 questions)
    │   ├── graphrag_test_suite_vol_8.json  # Multi-hop test queries (Vol 8: 25 questions)
    │   ├── graphrag_test_suite_vol_9.json  # Multi-hop test queries (Vol 9: 25 questions)
    │   └── graphrag_test_suite_vol_10.json # Multi-hop test queries (Vol 10: 25 questions)
    │
    ├── src/                           # Core application backend source code
    │   ├── models.py                  # Pydantic data schemas, Chunk dataclass & node/edge types
    │   ├── api/                       # API server modules
    │   │   ├── conversation_manager.py# Multi-turn in-memory conversational session store
    │   │   ├── fastapi_service.py     # Port 8000 FastAPI server (Hybrid retrieval + Qwen/Claude)
    │   │   └── inference_server.py    # Port 8080 standalone Llama-3.1 extraction API server
    │   ├── extraction/                # Document transformation & indexing modules
    │   │   ├── graph_builder.py       # LLM prompt extraction for entities & relations
    │   │   ├── graph_io.py            # High-performance orjson graph serialization/deserialization
    │   │   ├── keyword_index.py       # Case-preserving BM25 sparse indexer & searcher
    │   │   └── vector_embed.py        # BGE-large dense vector encoder & ChromaDB upsert manager
    │   ├── ingestion/                 # Raw document ingestion & metadata tracking
    │   │   ├── parser.py              # Unstructured layout parser & tiktoken token chunker
    │   │   ├── sharepoint_client.py   # Microsoft Graph REST API async client for SharePoint
    │   │   └── tracker.py             # SHA256 file deduplication tracker (ingestion_log.json)
    │   └── retrieval/                 # Multi-path search, routing, and reranking modules
    │       ├── hybrid_search.py       # Vector + Graph BFS + BM25 tri-hybrid RRF search engine
    │       ├── query_router.py        # Qwen structured query analyzer (intent, entities, seeds)
    │       └── reranker.py            # BGE cross-encoder reranker with sigmoid relevance gating
    │
    ├── systemd_configs/               # Linux OS service and timer automation units
    │   ├── graphrag_ingest.service    # Systemd service running daily_cycle.sh with jemalloc
    │   ├── graphrag_ingest_24_7.timer # Systemd timer polling hourly for 24/7 ingestion runs
    │   └── graphrag_ingest_nightly.timer # Systemd timer triggering nightly batch runs (9 PM IST)
    │
    └── tools/                         # Maintenance, benchmarking, and telemetry scripts
        ├── backup_db.py               # Rolling 14-day tar.gz database backup utility
        ├── mock_api.py                # Dummy FastAPI port 8000 server for GUI design on Windows
        ├── run_eval.py                # Automated benchmark evaluator for query_eso test suites
        ├── setup_storage_tiers.py     # Storage initialisation script setting up HDD vs SSD dirs
        └── telemetry_dashboard.py     # Live terminal dashboard displaying tokens/sec, ETA & rate
```

---

## 4. Comprehensive File-by-File Technical Dictionary

### 4.1 Root Documentation & Governance Files

| File Name | Description & Purpose |
|---|---|
| `AGENTS.md` | Defines agent roles (Planner, Coder, Tester, Security), the multi-session coordination protocol, non-negotiable architectural laws, and the strict two-machine rule (edit on Windows, run on Arch Linux). |
| `CLAUDE.md` | The authoritative technical specification for the project. Outlines hardware profiles, exact model weights, VRAM budgets, server port rules, bug history, and the complete "DO NOT" list. |
| `MASTER_CONTEXT.md` | Single historical source of truth absorbing Phase 2 and Phase 3 changes. Documents hardware performance, memory allocator mandates (`jemalloc`), and two-port architecture evolution. |
| `FRONTEND.md` | Comprehensive architectural specification for the PyQt6 desktop GUI client running natively under GNOME on Arch Linux. Details layout splits, QSS styling, and dependencies. |
| `ROUTINES.md` | Operational manual containing step-by-step procedures for server startup, ingestion execution, evaluation benchmarking, database backups, and disaster recovery. |
| `UNIFIED_MEMORY.md` | Live agent coordination blackboard tracking current task status, phase gates, active coder instructions, and architectural milestones. |
| `docs/DESIGN_SYSTEM.md` | Canonical design system for GraphRAG Platform. Governs editorial typography (Cormorant Garamond, DM Sans, DM Mono), warm neutral color palette, 8pt spacing grid, and component blueprints. |
| `CHANGES_SUMMARY.md` | Chronological append-only changelog documenting every modification made by agents across all project phases. |
| `CLAUDE_UPDATES_2026-06-20.md` | Archived phase proposal capturing Phase 2 additions: KnowledgeTab, `prune_document.py`, AccordionAIMessage, and PruningWorker. |
| `CLAUDE_UPDATES_2026-06-29.md` | Archived phase proposal capturing Phase 3 additions: Zombie lock fix, ServerManager, quarantine routing, and UI bug patches. |
| `CLAUDE_UPDATES_2026-06-30_phase4.md` | Phase 4 update proposal documenting the GraphRAG Editorial Design System Qt translation, font loading via QFontDatabase, and watermark policy enforcement. |
| `CLAUDE_UPDATES_2026-07-13.md` | Architectural hardening proposal addressing token collapse mitigation in Llama 3.1 8B, positive imperative system prompts, and the Phase 5 parallel ingestion roadmap. |

---

### 4.2 Skills Directory (`skills/`)

| File Name | Description & Purpose |
|---|---|
| `skills/SKILL.md` | Master engineering doctrine codifying non-negotiable constraints: VRAM layer allocation, atomic file writes (`tempfile` + `os.replace`), list-form `subprocess.Popen` (never `shell=True`), and port sanitation. |
| `skills/SKILL_GUI.md` | Complete build specification for the Phase 1 PyQt6 desktop application, covering non-blocking Qt event loop rules, JSON state IPC, telemetry workers, and PyVis integration. |
| `skills/SKILL_PHASE2.md` | Phase 2 architecture blueprint introducing granular document pruning, the KnowledgeTab, collapsible source accordions, and exhaustive QSS token mappings. |
| `skills/SKILL_PHASE4_UI.md` | Direct Qt translation of `docs/DESIGN_SYSTEM.md`. Defines `FontLoader`, token mapping dictionaries, and the removal of all legacy Catppuccin Mocha tokens. |

---

### 4.3 Engine Root & Lifecycle Scripts (`graphrag_engine/`)

| File Name | Description & Purpose |
|---|---|
| `.env` | Local environment configuration on the server (locked to `chmod 444`). Contains model paths, context window lengths, API keys, and database directory locations. |
| `.env.example` | Template environment file outlining mandatory configuration keys for local and cloud deployment. |
| `daily_cycle.sh` | Shell script executed by systemd timers. Scans the unprocessed pool; if PDFs exist, launches `batch_coordinator.py` under jemalloc; otherwise, runs `validate_system.py`. |
| `graphrag-api.service` | Systemd service definition running the FastAPI query server (`src.api.fastapi_service:app`) on port 8000 as a background system daemon. |
| `local_stability_report.log` | Historical telemetry log from running `run_local_stability_test.py`, recording 10 sequential successful queries and average latency. |
| `prune_document.py` | Standalone CLI utility for atomic 4-step document pruning: deletes vectors from ChromaDB, triggers BM25 rebuild, trims graph nodes/edges, and moves the PDF to `pruned/`. |
| `query_engine.py` | Standalone CLI hybrid retrieval and synthesis engine. Performs BGE query embedding, ChromaDB lookup, 2-hop graph extraction, and local LLM context synthesis. |
| `requirements.txt` | Python project dependencies specifying exact versions for PyTorch, sentence-transformers, ChromaDB, rank-bm25, NetworkX, PyQt6, and FastAPI. |
| `run_ingestion.py` | Main ingestion CLI pipeline. Coordinates layout parsing, OCR fallback, vector embeddings, Llama extraction via port 8080, MultiDiGraph creation, and rollback safety. |
| `run_local_stability_test.py` | Isolated local test harness that monkeypatches models and runs 10 test queries against a synthetic database to verify VRAM stability. |
| `validate_system.py` | System health check script verifying ChromaDB chunk counts, NetworkX graph integrity (node/edge sanity), and appending signed reports to `logs/health_report.log`. |

---

### 4.4 Backend Source Layer (`graphrag_engine/src/`)

#### Core Domain Models (`src/`)
* **`src/models.py`:** Defines core system data structures:
  * `Chunk`: Atomic ingestion unit storing `chunk_id`, `source_path`, `source_type`, `page_number`, `section_header`, `text`, `element_type`, `offset`, and metadata.
  * `VALID_NODE_TYPES` & `VALID_EDGE_TYPES`: Statutory ontology governing graph extraction.
  * `QueryAnalysis`: Retrieval guidance dataclass output by the query router.
  * `QueryRequest`, `QueryResponse`, `SourceReference`: Pydantic models for the FastAPI query interface.
  * `RankedResult`, `SearchResults`: Internal retrieval representation dataclasses.

#### API Subsystem (`src/api/`)
* **`src/api/conversation_manager.py`:** In-memory multi-turn session store managing conversation history (`Turn` and `Session` objects) for multi-query legal consultations. Trims sessions to `MAX_TURNS_PER_SESSION`.
* **`src/api/fastapi_service.py`:** Primary query server on port 8000. Loads `HybridSearchEngine`, `QueryRouter`, `reranker`, and Qwen/Claude models. Exposes `/query`, `/sessions/new`, `/sessions/{id}/clear`, and `/health`.
* **`src/api/inference_server.py`:** Standalone HTTP server on port 8080 wrapping Meta-Llama-3.1-8B-Instruct via `llama-cpp-python`. Used strictly during ingestion Stage 3 for entity extraction to prevent VRAM collisions with PyTorch.

#### Extraction & Indexing Subsystem (`src/extraction/`)
* **`src/extraction/graph_builder.py`:** Constructs the legal knowledge graph. Sends chunks to port 8080 using `EXTRACTION_PROMPT`, parses extracted JSON entities and relationships, and adds them to a NetworkX `MultiDiGraph`.
* **`src/extraction/graph_io.py`:** High-performance graph serialization and deserialization. Uses `orjson` and NetworkX `node_link_data` / `node_link_graph` for fast disk reads/writes.
* **`src/extraction/keyword_index.py`:** Builds and queries the lexical search index using `BM25Okapi`. Preserves case and punctuation to allow exact matching of legal sections and statutory terms.
* **`src/extraction/vector_embed.py`:** Handles dense semantic embeddings using `BAAI/bge-large-en-v1.5`. Normalizes vectors to 1024 dimensions, creates ChromaDB collections with cosine distance, and upserts chunk batches.

#### Ingestion Subsystem (`src/ingestion/`)
* **`src/ingestion/parser.py`:** Layout-aware document parser supporting PDF, DOCX, XLSX, CSV, and HTML. Uses `unstructured.partition.auto` (`strategy="fast"`), `openpyxl`, and `tiktoken` chunking (max 700 tokens). Tracks section headers.
* **`src/ingestion/sharepoint_client.py`:** Async client using `msal` and `aiohttp` to authenticate with Microsoft Graph API, crawl document libraries, handle rate limits (HTTP 429), and download PDFs.
* **`src/ingestion/tracker.py`:** SHA256-based deduplication tracker persisting status in `data/ingestion_log.json`. Prevents duplicate processing and detects modified files.

#### Retrieval Subsystem (`src/retrieval/`)
* **`src/retrieval/hybrid_search.py`:** Core tri-hybrid retrieval engine orchestrating Path 1 (ChromaDB vector search), Path 2 (NetworkX 2-hop BFS graph traversal), and Path 3 (BM25 lexical search). Combines hits via Reciprocal Rank Fusion (RRF, $k=60$).
* **`src/retrieval/query_router.py`:** Uses local Qwen3.6-12B in thinking mode to analyze queries. Extracts intent classification, legal entities, graph seed labels, and expanded queries.
* **`src/retrieval/reranker.py`:** Employs `BAAI/bge-reranker-v2-m3` CrossEncoder on CUDA to score (query, chunk) candidate pairs. Applies sigmoid normalization and filters candidates using the $0.15$ relevance gate.

---

### 4.5 Frontend Desktop Application (`graphrag_engine/gui/`)

#### Core Application & Styling
* **`gui/main.py`:** Master application entry point. Implements `FontLoader` (loads Cormorant Garamond, DM Sans, and DM Mono via `QFontDatabase`), `ThemeLoader` (resolves design tokens), and initializes `GraphRAGMainWindow` with the 3 primary tabs.
* **`gui/api_client.py`:** Provides background QThreads for HTTP interactions: `HealthCheckWorker` (polls `/health`) and `QueryWorker` (sends queries to port 8000).
* **`gui/styles.qss`:** Legacy Catppuccin Mocha stylesheet (preserved for historical fallback).
* **`gui/styles/theme.qss`:** Comprehensive QSS stylesheet fully translated to the GraphRAG Editorial Design System, styling buttons, cards, headers, tables, scrollbars, and splitters.

#### Services & State Management
* **`gui/services/server_manager.py`:** Manages FastAPI server lifecycle on port 8000. Detects bound ports via TCP socket checks, executes `sudo fuser -k 8000/tcp` cleanup, and launches uvicorn detached.
* **`gui/state/state_manager.py`:** Atomic JSON IPC manager reading and writing `data/gui_state.json`. Features `psutil.pid_exists()` checks to heal zombie locks within 1000ms.

#### UI Tabs (`gui/tabs/`)
* **`gui/tabs/ingestion_tab.py`:** Tab 1 interface. Features Start/Pause/Stop ingestion controls, QFileSystemWatcher tracking staging/archive/quarantine folders, telemetry status cards, and live streaming subprocess logs.
* **`gui/tabs/query_tab.py`:** Tab 2 interface. Chat panel with model mode selector (Local Qwen / Claude Sonnet / GPT-4o-mini), QSplitter layout, and integrated PyVis interactive graph visualizer.
* **`gui/tabs/knowledge_tab.py`:** Tab 3 interface. Async archive file table (`ArchiveLoaderWorker`) displaying document name, size, and date, with per-document atomic "Prune" buttons.

#### UI Widgets (`gui/widgets/`)
* **`gui/widgets/accordion_message.py`:** Collapsible chat bubble widget. Displays answer text alongside an expandable "View Source Evidence" accordion panel showing cited passages and relevance scores.
* **`gui/widgets/graph_view.py`:** Integrates `QWebEngineView` and `pyvis.network.Network`. Generates a physics-based interactive graph and uses a `QWebChannel` bridge to highlight active citation nodes.
* **`gui/widgets/mutual_exclusion_dialog.py`:** Modal dialog enforcing VRAM protection. Warns users when attempting conflicting operations (e.g., querying while ingestion is running).
* **`gui/widgets/spell_edit.py`:** Custom `QTextEdit` featuring real-time spellchecking via `SpellChecker` with red underlines and right-click spelling suggestion menus.

#### Worker Threads (`gui/workers/`)
* **`gui/workers/ingestion_worker.py`:** Background QThread launching `batch_coordinator.py` under jemalloc and streaming stdout lines to the GUI.
* **`gui/workers/pruning_worker.py`:** Background QThread executing `prune_document.py` in a subprocess, parsing step progress markers (10%, 35%, 60%, 85%, 100%), and updating state.
* **`gui/workers/query_worker.py`:** Dedicated QThread executing HTTP POST requests to `http://127.0.0.1:8000/query` with 120-second timeout handling.
* **`gui/workers/telemetry_worker.py`:** 1000ms polling QThread reading GPU utilization and VRAM via `pynvml`, CPU metrics via `psutil`, and IPC state via `StateManager`.

---

### 4.6 Infrastructure, Tools & Systemd

#### Infrastructure (`graphrag_engine/infrastructure/`)
* **`infrastructure/Dockerfile`:** Docker build recipe using NVIDIA CUDA 12.4.1 base, installing Python 3.11, PyTorch, and compiling `llama-cpp-python` with CUDA.
* **`infrastructure/docker-compose.yml`:** Docker Compose file reserving all NVIDIA GPU capabilities and mounting data, models, and ingestion directories.
* **`infrastructure/deploy_arch.sh`:** Automated Arch Linux shell script installing pacman packages, setting up pyenv, configuring virtualenv, and downloading BGE embeddings.
* **`infrastructure/patch_llama_cpp.sh`:** Utility script forcing clean re-installation of `llama-cpp-python` with `-DGGML_CUDA=on` to support IQ quantization formats.
* **`infrastructure/setup.sh`:** Quick-start virtual environment setup script.

#### Systemd Automation (`graphrag_engine/systemd_configs/`)
* **`systemd_configs/graphrag_ingest.service`:** Systemd service unit configured to run `daily_cycle.sh` under `LD_PRELOAD=/usr/lib/libjemalloc.so` and expandable CUDA segments.
* **`systemd_configs/graphrag_ingest_24_7.timer`:** Hourly poll timer unit activating the ingestion service continuously.
* **`systemd_configs/graphrag_ingest_nightly.timer`:** Off-hours timer triggering ingestion at 21:00 (9:00 PM IST) daily to prevent daytime workstation disruption.

#### Tools & Benchmarks (`graphrag_engine/tools/`)
* **`tools/backup_db.py`:** Backup automation script compressing `data/` into timestamped `.tar.gz` archives on bulk HDD storage, enforcing a 14-day rolling retention policy.
* **`tools/mock_api.py`:** Lightweight mock FastAPI server returning static answers, sources, and graph nodes for local frontend GUI development on Windows.
* **`tools/run_eval.py`:** Comprehensive benchmark runner posting 100 queries from `query_eso/` test suites to the query server and verifying recall against expected accounting standards.
* **`tools/setup_storage_tiers.py`:** Initializes two-tier storage layout: creates `staging`, `processing`, `archive`, `quarantine` on HDD and `chroma_db`, `bm25_index`, `knowledge_graph` on SSD.
* **`tools/telemetry_dashboard.py`:** Terminal dashboard streaming live metrics from `logs/ingestion_metrics.csv` and the unprocessed pool (tokens/sec, average file time, ETA).

#### Ingestion Mouth & SharePoint
* **`ingestion_mouth/batch_coordinator.py`:** Production batch orchestrator. Moves files from `unprocessed_pool` to `staging`, verifies requirements, and runs `run_ingestion.py` in a subprocess.
* **`ingestion_data/sync_sharepoint.py`:** Synchronization script skeleton for fetching document deltas from Azure SharePoint via rclone / Graph SDK.

#### Evaluation Test Suites (`graphrag_engine/query_eso/`)
* **`query_eso/graphrag_evaluator.py`:** Direct in-memory evaluation script importing the native engine, executing benchmark queries, and calculating retrieval recall scores.
* **`graphrag_test_suite_vol_1.json` through `vol_10.json`:** 10 volumes comprising 250 curated multi-hop compliance test cases across Indian Accounting Standards (AS 1 through AS 29, Ind AS, and guidance notes), specifying difficulty, target standards, and hop types.

---

## 5. Storage Tiering & Data Flow Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            STORAGE TIER TOPOLOGY                            │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ FAST NVMe SSD TIER (/home/.../data)  │ BULK MECHANICAL HDD TIER (/mnt/...)  │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ • chroma_db/ (Vector Embeddings)     │ • unprocessed_pool/ (Incoming PDFs)  │
│ • bm25_index/ (BM25 Okapi Sparse PKL)│ • staging/ (Active Batch Queue)      │
│ • knowledge_graph.json (MultiDiGraph)│ • archive/ (Processed Master PDFs)   │
│ • ingestion_log.json (SHA256 Tracker)│ • quarantine/ (Corrupt/Failed Files) │
│ • gui_state.json (Atomic IPC File)   │ • pruned/ (De-indexed Document PDFs) │
│ • models/ (All GGUF & HuggingFace)   │ • backups/ (14-Day Rolling Tarballs) │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

---

## 6. System Verification & Key Insights

1. **VRAM Safety:** Strict process and port isolation ensures the system never exceeds 10.4GB of the 12GB VRAM pool at query time, or 11.0GB at ingestion time.
2. **Deterministic Citations:** Inline hexadecimal citations (e.g. `[01a8f94847a6c3af]`) directly link generated statutory answers back to source PDF pages and section headers.
3. **Resilience & Self-Healing:** The combination of `batch_coordinator.py` subprocess isolation, `FileLock` mechanisms, atomic JSON writes, and `psutil.pid_exists` liveness checks prevents corrupted database states and heals zombie GUI locks within 1 second.
4. **Code Quality & Watermark Policy:** Zero attribution comments exist in production source code, ensuring pristine corporate ownership under the GraphRAG Platform brand guidelines.
