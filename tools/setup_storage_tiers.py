#!/usr/bin/env python3
"""
Two-tier storage strategy for GraphRAG Engine.

This script sets up the directory structure for a two-tier storage system:
- HDD (High Capacity, Slower): For staging, archive, and quarantine of raw data.
- SSD (Fast Access): For frequently accessed indices and knowledge graph.

Directories created:
  HDD:
    staging: Temporary storage for incoming files before processing.
    archive: Long-term storage of successfully processed files.
    quarantine: Isolation for failed or problematic files.
    processing: (Reserved for future use)

  SSD:
    chroma_db: Vector storage for fast similarity search.
    bm25_index: Keyword-based search index.
    knowledge_graph: Parent directory for knowledge graph storage (graph files).
"""

import os
from pathlib import Path



def main() -> None:
    # Read base paths from environment with fallbacks
    hdd_base = Path(os.getenv("HDD_BASE_PATH", "data/ingestion_pool"))
    ssd_base = Path(os.getenv("SSD_BASE_PATH", "./data"))

    # Define HDD directories
    hdd_dirs = [
        hdd_base / "staging",
        hdd_base / "processing",
        hdd_base / "archive",
        hdd_base / "quarantine",
    ]

    # Define SSD directories
    ssd_dirs = [
        ssd_base / "chroma_db",
        ssd_base / "bm25_index",
        ssd_base / "knowledge_graph",  # Parent directory for knowledge graph files
    ]

    all_dirs = hdd_dirs + ssd_dirs

    for dir_path in all_dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            if dir_path.exists():
                print(f"Already exists: {dir_path}")
            else:
                print(f"Created: {dir_path}")
        except Exception as e:
            print(f"Error creating {dir_path}: {e}")


if __name__ == "__main__":
    main()