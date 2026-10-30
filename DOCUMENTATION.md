# GraphRAG Engine — Technical Reference & Architecture Documentation

> **Architected & Developed by Joel Anthony ([@jvag15](https://github.com/jvag15))**  
> **Contact:** `mail@uncoalesced.com`  
> **Status:** Closed Portfolio Prototype (Unmaintained — Open for Forking)

---

## 1. Multi-Hop Hybrid Retrieval Mathematics

Standard vector similarity alone suffers from precision decay on complex statutory queries. GraphRAG deploys Reciprocal Rank Fusion (RRF) across three orthogonal retrieval paths:

$$RRF\_Score(d \in D) = \sum_{m \in M} \frac{w_m}{k + r_m(d)}$$

Where:
- $M = \{\text{Dense Vector}, \text{Knowledge Graph 2-Hop}, \text{Sparse BM25}\}$
- $r_m(d)$ is the 1-based rank position of candidate document $d$ in retrieval method $m$.
- $k = 60$ is the smoothing constant to avoid outlier bias.
- $w_m$ represents channel weighting ($w_{\text{vector}} = 1.0$, $w_{\text{graph}} = 1.2$, $w_{\text{bm25}} = 0.8$).

Following fusion, candidates are passed to a Cross-Encoder reranker:
$$\text{Relevance Score} = \sigma(\text{CrossEncoder}(q, d))$$
Any candidate scoring below the $0.15$ threshold is discarded. If all candidates fail the threshold, the system triggers a verified rejection rather than generating an ungrounded hallucination.

---

## 2. Knowledge Graph Architecture (`src/extraction/graph_builder.py`)

- **Graph Model:** Directed Multi-Graph stored via `networkx.MultiDiGraph`.
- **Entity Extraction:** Legal entities (Standard Codes, Section Numbers, Regulatory Bodies, Compliance Conditions) extracted using local quantized LLM prompts.
- **Persistence:** High-speed binary or JSON serialization using `orjson`.
- **Traversal:** On incoming queries, recognized seed entities are queried via Breadth-First Search (BFS) up to 2 hops deep with an edge ceiling of 50 to form a localized semantic subgraph.

---

## 3. Storage Hierarchy & Atomic Pruning

```
                  Storage Tiers
       ┌──────────────────────────────────┐
       │     Fast NVMe / SSD Tier         │
       │  - ChromaDB Vector Embeddings    │
       │  - BM25 Pickled Corpus Index     │
       │  - Active NetworkX Graph File    │
       └────────────────┬─────────────────┘
                        │
                        ▼
       ┌──────────────────────────────────┐
       │     Capacity Storage Tier        │
       │  - Raw Staged Ingestion Pool     │
       │  - Processed Archive Spool       │
       │  - 14-Day Rolling SQLite Backups │
       └──────────────────────────────────┘
```

When a document is pruned (`prune_document.py`):
1. **ChromaDB**: All chunks tagged with `doc_name` are deleted by ID.
2. **BM25**: Active vector store documents are queried, and the sparse index is atomically re-compiled.
3. **Knowledge Graph**: Subgraph nodes and edges referencing the target document are removed.
4. **Telemetry**: Document status is marked as `PRUNED` in the tracking database.

---

## 4. Desktop Client Engineering (`gui/`)

The desktop client is written in PyQt6 with a custom editorial design system (`gui/styles/theme.qss`):
- **Hardware Telemetry Worker:** Background `QThread` polling NVIDIA Management Library (`pynvml`) for VRAM usage and temperature, and `psutil` for host RAM and CPU load every 1,000ms.
- **Accordion Citation Bubbles:** Custom collapsible Qt widgets that parse inline hex tags (`[01a8f94847a6c3af]`) and render full source context on click.
- **Interactive Graph Canvas:** PyQt6 `QWebEngineView` integrating PyVis physics simulation with live node clustering.

---

*Author: Joel Anthony ([@jvag15](https://github.com/jvag15)) — Portfolio Release*
