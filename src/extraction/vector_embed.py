import os
import torch
import chromadb
from pathlib import Path
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from src.models import Chunk


def load_embedding_model(model_path: str = "BAAI/bge-large-en-v1.5", device: str = "cuda") -> SentenceTransformer:
    if device == "cuda" and not torch.cuda.is_available():
        print("WARNING: CUDA not available. Falling back to CPU. Embedding will be slow.")
        device = "cpu"

    model = SentenceTransformer(
        model_path,
        trust_remote_code=True,
        device=device
    )

    if device == "cuda":
        print(f"Embedding model loaded on GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM used: {torch.cuda.memory_allocated(0) / 1e9:.2f} GB")

    return model


def embed_chunks(model: SentenceTransformer, chunks: list[Chunk], batch_size: int = 64) -> list[list[float]]:
    texts = [c.text for c in chunks]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True
    )
    return embeddings.tolist()


def embed_query(model: SentenceTransformer, query: str) -> list[float]:
    embeddings = model.encode(
        [f"Represent this sentence for searching relevant passages: {query}"],
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True
    )
    return embeddings[0].tolist()


def get_chroma_collection(path: str, collection_name: str, embedding_dim: int = 1024):
    client = chromadb.PersistentClient(path=path)
    existing = client.list_collections()
    for col in existing:
        if col.name == collection_name:
            try:
                test = client.get_collection(collection_name)
                stored_dim = test.metadata.get("embedding_dim")
                if stored_dim and int(stored_dim) != embedding_dim:
                    print(f"WARNING: Existing collection has dim {stored_dim}, "
                          f"model produces {embedding_dim}. Deleting collection.")
                    client.delete_collection(collection_name)
            except Exception:
                pass
                
    return client.get_or_create_collection(
        name=collection_name,
        metadata={
            "hnsw:space": "cosine",
            "embedding_dim": str(embedding_dim)
        }
    )


def upsert_chunks(collection, chunks: list[Chunk], embeddings: list[list[float]]):
    batch_size = 64
    for i in tqdm(range(0, len(chunks), batch_size), desc="Upserting to ChromaDB"):
        batch_chunks = chunks[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]
        
        metadatas = []
        for c in batch_chunks:
            meta = {
                "source_path": c.source_path,
                "source_type": c.source_type,
                "page_number": c.page_number if c.page_number is not None else -1,
                "section_header": c.section_header if c.section_header is not None else "",
                "element_type": c.element_type,
                "offset": c.offset
            }
            # Sanitize metadata: convert any Path objects to string
            sanitized_meta = {}
            for key, value in meta.items():
                if isinstance(value, Path):
                    sanitized_meta[key] = str(value)
                else:
                    sanitized_meta[key] = value
            metadatas.append(sanitized_meta)

        collection.upsert(
            ids=[c.chunk_id for c in batch_chunks],
            embeddings=batch_embeddings,
            documents=[c.text for c in batch_chunks],
            metadatas=metadatas
        )
