import pickle
import numpy as np
from pathlib import Path
from rank_bm25 import BM25Okapi
from src.models import Chunk


def build_bm25_index(chunks: list[Chunk], index_path: str):
    """
    IMPORTANT: Do NOT lowercase, stop-word filter, or lemmatise the tokens.
    Legal identifiers (Section 17, GSTIN, Form GSTR-3B, etc.) must match exactly.
    """
    tokenized_corpus = [chunk.text.split() for chunk in chunks]   # preserve case
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    chunk_texts = [chunk.text for chunk in chunks]

    bm25 = BM25Okapi(tokenized_corpus)

    Path(index_path).parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "wb") as f:
        pickle.dump({
            "bm25": bm25,
            "chunk_ids": chunk_ids,
            "chunk_texts": chunk_texts
        }, f)

    print(f"BM25 index built: {len(chunks)} documents indexed at {index_path}")


def load_bm25_index(index_path: str) -> dict:
    with open(index_path, "rb") as f:
        return pickle.load(f)


def bm25_search(index_data: dict, query: str, top_k: int = 10) -> list[dict]:
    bm25 = index_data["bm25"]
    chunk_ids = index_data["chunk_ids"]
    chunk_texts = index_data["chunk_texts"]

    # Preserve case — we want exact matches on "Section 17", "GSTIN", etc.
    tokenized_query = query.split()
    scores = bm25.get_scores(tokenized_query)

    top_indices = np.argsort(scores)[::-1][:top_k]

    return [
        {
            "chunk_id": chunk_ids[i],
            "text": chunk_texts[i],
            "score": float(scores[i])
        }
        for i in top_indices
        if scores[i] > 0
    ]


def build_bm25_from_chroma(chroma_path: str = None, collection_name: str = None, index_path: str = None):
    """Rebuilds the BM25 index from active chunks stored in ChromaDB."""
    import os
    import chromadb

    chroma_path = chroma_path or os.environ.get("CHROMA_PATH", "data/chroma_db")
    collection_name = collection_name or os.environ.get("CHROMA_COLLECTION", "legal_chunks")
    index_path = index_path or os.environ.get("BM25_INDEX_PATH", "data/bm25_index/bm25.pkl")

    try:
        client = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_or_create_collection(name=collection_name)
        results = collection.get()

        chunks = []
        if results and "ids" in results:
            for chunk_id, text in zip(results["ids"], results.get("documents", [])):
                if text:
                    chunks.append(Chunk(chunk_id=chunk_id, text=text, doc_name="", page_num=0, token_count=len(text.split())))

        if chunks:
            build_bm25_index(chunks, index_path)
            print(f"BM25 index successfully rebuilt from ChromaDB: {len(chunks)} chunks.")
        else:
            print("No chunks found in ChromaDB for BM25 rebuild.")
    except Exception as e:
        print(f"Error rebuilding BM25 from Chroma: {e}")
