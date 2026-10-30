# /brag Video Plan: GraphRAG Engine

## 1. Product Summary
- **Product:** GraphRAG Engine — Enterprise Statutory & Legal Intelligence Platform
- **Target Audience:** Legal engineers, compliance auditors, AI researchers
- **Tagline:** 3-Path Hybrid Search with Dense Vectors, Subgraphs, and Exact Lexical Reranking
- **Angle:** Standard RAG hallucinates legal identifiers and misses multi-hop statutory hierarchies. GraphRAG combines BGE dense vectors, 2-hop NetworkX subgraphs, and BM25Okapi exact matching, scoring candidates with Reciprocal Rank Fusion and a strict 0.15 relevance gate.
- **Audio Direction:** Intentionally silent (no music) per repository specifications.

## 2. Storyboard Arc
1. **Scene 1 (0-3s): The Problem** — Semantic embeddings failing on section clauses ("Section 17(5)(c)"), fragmenting multi-hop standards, and risking calculation hallucinations.
2. **Scene 2 (3-6.5s): 3-Path Hybrid Architecture** — Dense Vectors (BGE-Large), 2-Hop Knowledge Subgraphs (NetworkX BFS), and Sparse BM25 exact matching.
3. **Scene 3 (6.5-10s): Fusion & Strict Grounding** — Reciprocal Rank Fusion, Cross-Encoder M3 reranker, strict 0.15 cutoff, and hexadecimal chunk citations `[01a8f94847a6c3af]`.
4. **Scene 4 (10-13s): Desktop Control Platform** — PyQt6 GUI with live GPU/VRAM hardware telemetry, interactive PyVis graph visualization, and air-gapped local LLM inference.
5. **Scene 5 (13-16s): Outro & Attribution** — Architected and developed by Joel Anthony (@jvag15) — Open source portfolio prototype under MIT license.
