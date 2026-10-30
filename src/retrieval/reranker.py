# src/retrieval/reranker.py
"""
Cross-encoder reranking of retrieved chunks against the query.
"""

import os
from sentence_transformers import CrossEncoder
import torch
import numpy as np
from typing import List, Tuple
from src.models import RankedResult

RELEVANCE_THRESHOLD = 0.15  # sigmoid-normalised score below this = insufficient context


def load_reranker(model_path: str) -> CrossEncoder:
    reranker = CrossEncoder(model_path, device="cuda")
    print(f"Reranker loaded. VRAM used: {torch.cuda.memory_allocated(0) / 1e9:.2f} GB")
    return reranker


def rerank_chunks(
    reranker: CrossEncoder,
    query: str,
    chunks: List[RankedResult],
    top_k: int = 10
) -> Tuple[List[RankedResult], bool]:
    """
    Returns (reranked_chunks, has_sufficient_context).
    has_sufficient_context is False if all scores below RELEVANCE_THRESHOLD.
    """
    if not chunks:
        return [], False

    pairs = [(query, chunk.text) for chunk in chunks]
    scores = reranker.predict(pairs, show_progress_bar=False)

    # Normalise to 0-1
    normalised = 1 / (1 + np.exp(-scores))  # sigmoid

    # Sort by reranker score descending
    sorted_indices = np.argsort(normalised)[::-1][:top_k]
    reranked = []
    for idx in sorted_indices:
        chunk = chunks[idx]
        chunk.reranker_score = float(normalised[idx])
        reranked.append(chunk)

    # Check if any chunk has sufficient relevance
    has_sufficient_context = any(c.reranker_score >= RELEVANCE_THRESHOLD for c in reranked)

    return reranked, has_sufficient_context