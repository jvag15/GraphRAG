# GraphRAG Engine — Enterprise Legal & Statutory Compliance Intelligence

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52.svg?logo=qt&logoColor=white)](https://www.qt.io/)
[![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB-orange.svg)](https://www.trychroma.com/)
[![NetworkX](https://img.shields.io/badge/KnowledgeGraph-NetworkX-blueviolet.svg)](https://networkx.org/)

> **Architected & Developed by Joel Anthony ([@jvag15](https://github.com/jvag15))**  
> **Contact:** `mail@uncoalesced.com`

---

> [!IMPORTANT]
> ### Project Status: Closed & Unmaintained
> This repository is a personal portfolio showcase of an offline-first, hybrid GraphRAG legal intelligence platform architected and developed by Joel Anthony. **This repository is closed and will NOT be maintained further.**
> 
> You are fully welcome and encouraged to fork, adapt, and build upon this codebase under the terms of the [MIT License](LICENSE).

---

## Executive Summary

Standard Retrieval-Augmented Generation (RAG) models fail when answering complex questions over dense statutory legal codes, Indian Accounting Standards (Ind AS), and regulatory compliance audits. Semantic embeddings alone miss exact legal statute references (e.g., *"Section 17(5)(h)"* vs *"Section 17(5)(c)"*), and cannot traverse multi-hop parent-child relationships across interconnected standards.

The **GraphRAG Engine** implements a **3-Path Hybrid Search** and reranking architecture that fuses:
1. **Dense Vector Retrieval** (`BAAI/bge-large-en-v1.5` over ChromaDB) for semantic conceptual match.
2. **2-Hop Subgraph Traversal** (NetworkX MultiDiGraph) for structural and cross-statutory entity relationships.
3. **Exact Lexical Indexing** (`BM25Okapi` without case folding) for strict statutory identifiers and section numbers.

Retrieved candidates are unified via **Reciprocal Rank Fusion (RRF)** and re-scored by a Cross-Encoder reranker (`BAAI/bge-reranker-v2-m3`) with a strict $0.15$ relevance gate before generation.

```
                                  [ User Query ]
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           │                            │                            │
           ▼                            ▼                            ▼
  [ Dense Vector Path ]        [ 2-Hop Graph Path ]        [ Sparse BM25 Path ]
   ChromaDB + BGE-Large      Entity Linking + BFS Subgraph   BM25 Exact Lexical
           │                            │                            │
           └────────────────────────────┼────────────────────────────┘
                                        │
                                        ▼
                         [ Reciprocal Rank Fusion (RRF) ]
                                        │
                                        ▼
                         [ Cross-Encoder Reranker M3 ]
                            (Strict Relevance Gate)
                                        │
                                        ▼
                         [ Grounded LLM Generation ]
                          Local Llama-3 / Cloud Sonnet
                                        │
                                        ▼
                       [ Verified Compliance Response ]
                         (With Inline Hex Source Citations)
```

---

## Key Capabilities

- **3-Path Hybrid Retrieval:** Fuses vector embeddings, knowledge subgraphs, and BM25 token matching.
- **Air-Gapped & Local Inference Support:** Complete offline capability via `llama-cpp-python` supporting quantized Llama-3-8B and Qwen models with GPU offloading.
- **Strict Compliance Grounding:** Prompt-engineered refusal to hallucinate numbers or domestic statutory interest rates; all claims anchored with chunk hexadecimal citations (e.g. `[a3c9f104e7]`).
- **Comprehensive Desktop GUI:** PyQt6 desktop workstation client featuring live hardware telemetry (NVML VRAM/psutil CPU), interactive PyVis knowledge graph visualizer, and collapsible citation accordions.
- **Atomic Document Pruner:** Command-line and GUI tooling for clean document pruning across ChromaDB vectors, BM25 indices, and NetworkX subgraphs simultaneously.
- **10-Volume Evaluation Benchmark:** Includes comprehensive test suites covering Indian Accounting Standards and multi-hop statutory scenarios.

---

## Repository Structure

```
GraphRAG/
├── docs/                 # Complete system specifications & design docs
│   ├── ARCHITECTURE.md   # Detailed multi-hop architectural blueprint
│   ├── FRONTEND.md       # Desktop GUI technical specifications
│   ├── DESIGN_SYSTEM.md  # Editorial design tokens and QSS guidelines
│   ├── OPERATIONS.md     # System administration & pipeline runbooks
│   ├── SYSTEM_DESIGN.md  # Unified memory and architectural history
│   └── specifications/   # Detailed implementation phase specs
├── gui/                  # PyQt6 Desktop Client
│   ├── main.py           # Application entrypoint
│   ├── styles/theme.qss  # Modern desktop stylesheet
│   ├── tabs/             # Ingestion, Knowledge Graph, and Query tabs
│   ├── widgets/          # Accordion citations, PyVis graph views
│   └── workers/          # Background QThread workers
├── src/                  # Core Python Engine
│   ├── api/              # FastAPI endpoints & session manager
│   ├── extraction/       # Graph builder, vector embedder, BM25 indexer
│   ├── ingestion/        # Document parsers (PDF, DOCX, XLSX, SharePoint)
│   └── retrieval/        # Hybrid search, query router, reranker
├── tools/                # Backup engine, telemetry dashboard, eval runners
├── query_eso/            # 10-Volume statutory evaluation suites
├── query_engine.py       # Standalone CLI query interface
├── run_ingestion.py      # Automated ingestion orchestrator
├── prune_document.py     # Multi-index atomic document pruner
├── requirements.txt      # Python dependencies
└── .env.example          # Environment configuration template
```

---

## Quickstart

### 1. Installation
Clone the repository and install dependencies in a virtual environment:
```bash
git clone https://github.com/jvag15/GraphRAG.git
cd GraphRAG
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Environment Setup
Copy the configuration template:
```bash
cp .env.example .env
```
Configure your model paths (e.g. `LLAMA_MODEL_PATH=models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf`) or set `ANTHROPIC_API_KEY` for cloud fallback.

### 3. Start the FastAPI Service
```bash
uvicorn src.api.fastapi_service:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Launch the Desktop GUI
```bash
python gui/main.py
```

---

## Author & Attribution

- **Architect & Developer:** Joel Anthony ([@jvag15](https://github.com/jvag15))
- **Email:** `mail@uncoalesced.com`
- **License:** [MIT License](LICENSE)
