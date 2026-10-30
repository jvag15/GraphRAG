import os
import re
import numpy as np
import networkx as nx
import chromadb
from sentence_transformers import SentenceTransformer
from typing import Optional

from src.models import RankedResult, SearchResults, QueryAnalysis
from src.extraction.keyword_index import load_bm25_index, bm25_search
from src.extraction.graph_io import load_graph
from src.extraction.vector_embed import embed_query
from src.retrieval.reranker import load_reranker, rerank_chunks


class HybridSearchEngine:
    def __init__(self):
        self.embed_model = None
        self.chroma_collection = None
        self.bm25_data = None
        self.graph: nx.MultiDiGraph | None = None
        self.reranker: Optional[object] = None  # CrossEncoder | None

    def load_indices(self):
        embed_path = os.environ["EMBED_MODEL_PATH"]
        device = os.environ.get("EMBED_DEVICE", "cuda")

        self.embed_model = SentenceTransformer(
            embed_path, trust_remote_code=True, device=device
        )

        client = chromadb.PersistentClient(path=os.environ["CHROMA_PATH"])
        self.chroma_collection = client.get_collection(os.environ["CHROMA_COLLECTION"])

        self.bm25_data = load_bm25_index(os.environ["BM25_INDEX_PATH"])

        self.graph = load_graph(os.environ["GRAPH_PATH"])

        print(f"Indices loaded. ChromaDB docs: {self.chroma_collection.count()}, "
              f"Graph nodes: {self.graph.number_of_nodes()}, edges: {self.graph.number_of_edges()}")

    def set_reranker(self, reranker):
        """Inject an externally created reranker instance."""
        self.reranker = reranker
        if reranker is not None:
            print("Reranker injected successfully")
        else:
            print("Reranker set to None")

    def search(self, query: str, top_k: int = 10, graph_hops: int = 2) -> SearchResults:
        # --- Path 1: Vector search ---
        query_embedding = embed_query(self.embed_model, query)

        vector_results = self.chroma_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )

        vector_hits = {}
        for i, chunk_id in enumerate(vector_results["ids"][0]):
            vector_hits[chunk_id] = {
                "text": vector_results["documents"][0][i],
                "metadata": vector_results["metadatas"][0][i],
                "score": 1.0 - vector_results["distances"][0][i]  # distance to similarity
            }

        # --- Path 2: Graph traversal ---
        seed_nodes = self._extract_seed_nodes(query)
        graph_chunk_ids, graph_path = self._graph_traverse(seed_nodes, hops=graph_hops)

        # --- Path 3: BM25 ---
        bm25_hits_raw = bm25_search(self.bm25_data, query, top_k=top_k)
        bm25_hits = {h["chunk_id"]: h for h in bm25_hits_raw}

        # --- RRF fusion ---
        all_chunk_ids = set(vector_hits.keys()) | set(graph_chunk_ids) | set(bm25_hits.keys())

        def rrf(rank: int, k: int = 60) -> float:
            return 1.0 / (k + rank + 1)

        rrf_scores = {cid: 0.0 for cid in all_chunk_ids}

        for rank, cid in enumerate(vector_hits.keys()):
            rrf_scores[cid] += rrf(rank)

        for rank, cid in enumerate(graph_chunk_ids):
            rrf_scores[cid] += rrf(rank)

        for rank, cid in enumerate(bm25_hits.keys()):
            rrf_scores[cid] += rrf(rank)

        sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)[:top_k]

        # Assemble final ranked results before reranking
        pre_rerank_results = []
        for cid in sorted_ids:
            if cid in vector_hits:
                meta = vector_hits[cid]["metadata"]
                text = vector_hits[cid]["text"]
                method = "vector"
            elif cid in bm25_hits:
                text = bm25_hits[cid]["text"]
                meta = {}
                method = "bm25"
            else:
                # From graph — look up text from BM25 index
                idx_map = {c: t for c, t in zip(
                    self.bm25_data["chunk_ids"], self.bm25_data["chunk_texts"]
                )}
                text = idx_map.get(cid, "")
                meta = {}
                method = "graph"

            pre_rerank_results.append(RankedResult(
                chunk_id=cid,
                text=text,
                source_path=meta.get("source_path", ""),
                section_header=meta.get("section_header") or None,
                retrieval_method=method,
                score=rrf_scores[cid]
            ))

        # Apply reranker if available
        if self.reranker is not None:
            try:
                reranked_results, has_sufficient_context = rerank_chunks(
                    self.reranker, query, pre_rerank_results, top_k=top_k
                )
            except Exception as e:
                print(f"Warning: Reranking failed: {e}")
                print("Falling back to RRF-only results")
                reranked_results = pre_rerank_results
                has_sufficient_context = len(pre_rerank_results) > 0  # Assume sufficient if we have results
        else:
            # No reranker available
            reranked_results = pre_rerank_results
            has_sufficient_context = len(pre_rerank_results) > 0  # Assume sufficient if we have results

        strategy = f"vector({len(vector_hits)}) + graph({len(graph_chunk_ids)}) + bm25({len(bm25_hits)})"
        if self.reranker is not None:
            strategy += " + reranker"

        return SearchResults(
            ranked_chunks=reranked_results,
            graph_path=graph_path,
            strategy_used=strategy,
            has_sufficient_context=has_sufficient_context
        )

    def _extract_seed_nodes(self, query: str) -> list[str]:
        """
        Find graph nodes matching entities mentioned in the query.
        Uses regex for section numbers, then fuzzy label matching.
        """
        # Extract section references like "Section 17", "Section 17(5)(a)", "s.17"
        section_pattern = re.compile(
            r'\b[Ss]ection\s+(\d+[\w()\[\]]*)|[Ss]\.\s*(\d+[\w()\[\]]*)', re.IGNORECASE
        )
        found_sections = [m.group(1) or m.group(2) for m in section_pattern.finditer(query)]

        seed_nodes = []
        for node_id, data in self.graph.nodes(data=True):
            label = data.get("label", "").lower()
            for sec in found_sections:
                if sec and sec.lower() in label:
                    seed_nodes.append(node_id)
                    break

        return list(set(seed_nodes))

    def _graph_traverse(self, seed_nodes: list[str], hops: int) -> tuple[list[str], list[str]]:
        """
        BFS from seed nodes, following ALL typed edges both directions.
        Returns (chunk_ids_of_reached_nodes, list_of_traversed_node_ids).
        """
        if not seed_nodes or not self.graph:
            return [], []

        visited = set()
        frontier = set(seed_nodes)
        traversal_path = list(seed_nodes)
        all_chunk_ids = []

        for _ in range(hops):
            next_frontier = set()
            for node_id in frontier:
                if node_id in visited:
                    continue
                visited.add(node_id)
                node_data = self.graph.nodes[node_id]
                cid = node_data.get("source_chunk_id")
                if cid and cid not in all_chunk_ids:
                    all_chunk_ids.append(cid)

                for _, neighbor, _ in self.graph.out_edges(node_id, data=True):
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
                        if neighbor not in traversal_path:
                            traversal_path.append(neighbor)

                for neighbor, _, _ in self.graph.in_edges(node_id, data=True):
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
                        if neighbor not in traversal_path:
                            traversal_path.append(neighbor)

            frontier = next_frontier

        return all_chunk_ids, traversal_path

    def get_stats(self) -> dict:
        return {
            "chroma_documents": self.chroma_collection.count() if self.chroma_collection else 0,
            "graph_nodes": self.graph.number_of_nodes() if self.graph else 0,
            "graph_edges": self.graph.number_of_edges() if self.graph else 0,
            "bm25_documents": len(self.bm25_data["chunk_ids"]) if self.bm25_data else 0,
        }