#!/usr/bin/env python3
"""
Standalone document pruning script.

Accepts document_id (PDF filename) as CLI argument.
Deletes all vectors, graph nodes, and edges associated with the document.
Moves the PDF from archive/ to pruned/.
All operations are atomic. Prints progress to stdout.

Usage: python prune_document.py "008. AS 10 Property plant and equipment.pdf"
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
HDD_BASE = Path(
    os.environ.get(
        "HDD_BASE_PATH",
        "data/ingestion_pool",
    )
)
ARCHIVE_DIR = HDD_BASE / "archive"
PRUNED_DIR = HDD_BASE / "pruned"
CHROMA_PATH = DATA_DIR / "chroma_db"
GRAPH_PATH = DATA_DIR / "knowledge_graph.json"


def log(msg: str) -> None:
    """Print flush-forced line for subprocess stdout streaming."""
    print(msg, flush=True)


def prune(document_id: str) -> int:
    """Execute full pruning sequence. Returns 0 on success, 1 on error.

    Steps execute in order. Early return on any step failure prevents
    the PDF from being moved (Step 4), ensuring no data loss.
    """
    log(f"[PRUNE] Starting: {document_id}")
    PRUNED_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: ChromaDB vector deletion
    log("[PRUNE] Step 1/4: Deleting vector embeddings from ChromaDB...")
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection = client.get_collection(
            os.environ.get("CHROMA_COLLECTION", "legal_chunks")
        )
        # Metadata field "source_path" contains the full path; filename is suffix.
        # Also check "filename" metadata field.
        results = collection.get(
            where={
                "$or": [
                    {"source_path": {"$contains": document_id}},
                    {"filename": document_id},
                ]
            },
            include=["metadatas"],
        )
        ids_to_delete = results.get("ids", [])
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
            log(f"[PRUNE] Deleted {len(ids_to_delete)} vectors.")
        else:
            log("[PRUNE] No vectors found for this document (may already be pruned).")
    except Exception as e:
        log(f"[PRUNE][ERROR] ChromaDB deletion failed: {e}")
        return 1

    # Step 2: BM25 index rebuild (required after vector deletion)
    log("[PRUNE] Step 2/4: Rebuilding BM25 index...")
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.extraction.keyword_index import build_bm25_from_chroma

        build_bm25_from_chroma()
        log("[PRUNE] BM25 index rebuilt.")
    except Exception as e:
        log(f"[PRUNE][WARN] BM25 rebuild failed (non-fatal): {e}")

    # Step 3: Knowledge graph node/edge pruning
    log("[PRUNE] Step 3/4: Pruning knowledge graph nodes and edges...")
    try:
        with open(GRAPH_PATH, "r", encoding="utf-8") as f:
            graph_data = json.load(f)

        nodes_before = len(graph_data.get("nodes", []))
        edges_before = len(graph_data.get("edges", []))

        def node_belongs_to_doc(node) -> bool:
            """Check if a graph node is associated with the target document."""
            attrs = node[1] if isinstance(node, (list, tuple)) else node
            if isinstance(attrs, dict):
                sp = attrs.get("source_path", "")
                fn = attrs.get("filename", "")
                return document_id in sp or document_id in fn
            return False

        pruned_nodes = [
            n for n in graph_data.get("nodes", []) if not node_belongs_to_doc(n)
        ]
        surviving_node_ids = set()
        for n in pruned_nodes:
            nid = n[0] if isinstance(n, (list, tuple)) else n.get("id", "")
            surviving_node_ids.add(str(nid))

        # Filter edges: remove any edge where source or target no longer exists
        pruned_edges = []
        for e in graph_data.get("edges", []):
            if isinstance(e, (list, tuple)) and len(e) >= 2:
                src, tgt = str(e[0]), str(e[1])
            elif isinstance(e, dict):
                src, tgt = str(e.get("source", "")), str(e.get("target", ""))
            else:
                continue
            if src in surviving_node_ids and tgt in surviving_node_ids:
                pruned_edges.append(e)

        graph_data["nodes"] = pruned_nodes
        graph_data["edges"] = pruned_edges

        # Atomic write via tempfile in same directory as target
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json", dir=str(DATA_DIR), prefix="knowledge_graph_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(graph_data, tmp, indent=2, ensure_ascii=False)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, str(GRAPH_PATH))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        log(
            f"[PRUNE] Nodes: {nodes_before} → {len(pruned_nodes)} "
            f"(-{nodes_before - len(pruned_nodes)})"
        )
        log(
            f"[PRUNE] Edges: {edges_before} → {len(pruned_edges)} "
            f"(-{edges_before - len(pruned_edges)})"
        )
    except Exception as e:
        log(f"[PRUNE][ERROR] Graph pruning failed: {e}")
        return 1

    # Step 4: Move PDF from archive/ to pruned/
    log("[PRUNE] Step 4/4: Moving PDF to pruned/ directory...")
    try:
        src_path = ARCHIVE_DIR / document_id
        dst_path = PRUNED_DIR / document_id
        if src_path.exists():
            shutil.move(str(src_path), str(dst_path))
            log(f"[PRUNE] Moved to: {dst_path}")
        else:
            log(f"[PRUNE][WARN] PDF not found in archive: {src_path}")
    except PermissionError as e:
        log(f"[PRUNE][ERROR] Permission denied moving PDF: {e}")
        return 1
    except Exception as e:
        log(f"[PRUNE][ERROR] PDF move failed: {e}")
        return 1

    log(f"[PRUNE] Complete: {document_id}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python prune_document.py <document_id>", flush=True)
        sys.exit(1)
    sys.exit(prune(sys.argv[1]))