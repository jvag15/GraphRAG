import os
import sys
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import networkx as nx
import chromadb

# Ensure environment variables are loaded
load_dotenv()

def run_validation():
    # Setup paths
    project_root = Path(__file__).resolve().parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_lines = []
    report_lines.append(f"System Validation Report - {timestamp}")
    report_lines.append("=" * 60)
    
    status = "HEALTHY"
    
    # 1. Check ChromaDB vector table availability
    try:
        chroma_path = os.environ.get("CHROMA_PATH", "data/chroma_db")
        collection_name = os.environ.get("CHROMA_COLLECTION", "legal_chunks")
        
        # Resolve path relative to project root if it is not absolute
        chroma_path_resolved = project_root / chroma_path if not Path(chroma_path).is_absolute() else Path(chroma_path)
        
        client = chromadb.PersistentClient(path=str(chroma_path_resolved))
        collection = client.get_collection(name=collection_name)
        count = collection.count()
        report_lines.append(f"[SUCCESS] ChromaDB initialized. Collection '{collection_name}' count: {count} chunks.")
    except Exception as e:
        status = "DEGRADED"
        report_lines.append(f"[FAILED] ChromaDB check failed: {e}")
        
    # 2. Check knowledge_graph.json sanity
    try:
        graph_path = os.environ.get("GRAPH_PATH", "data/knowledge_graph.json")
        graph_path_resolved = project_root / graph_path if not Path(graph_path).is_absolute() else Path(graph_path)
        
        if not graph_path_resolved.exists():
            raise FileNotFoundError(f"Knowledge graph file not found at {graph_path_resolved}")
            
        with open(graph_path_resolved, 'r', encoding='utf-8') as f:
            graph_data = json.load(f)
            
        # Try to load node-link graph
        G = nx.readwrite.json_graph.node_link_graph(graph_data)
        node_count = G.number_of_nodes()
        edge_count = G.number_of_edges()
        
        # Verify structure sanity (must not be empty)
        if node_count == 0:
            raise ValueError("Knowledge graph contains 0 nodes (potentially corrupt or uninitialized)")
            
        report_lines.append(f"[SUCCESS] NetworkX Knowledge Graph is valid. Nodes: {node_count}, Edges: {edge_count}.")
    except Exception as e:
        status = "DEGRADED"
        report_lines.append(f"[FAILED] Knowledge graph check failed: {e}")
        
    # 3. Append signed health report
    report_lines.append("=" * 60)
    report_lines.append(f"Overall Status: {status}")
    report_lines.append("Signed: GraphRAG System Auto-Validation Daemon")
    report_lines.append("\n")
    
    # Write to health report log
    health_report_path = logs_dir / "health_report.log"
    try:
        with open(health_report_path, "a", encoding='utf-8') as hf:
            hf.write("\n".join(report_lines))
        print(f"Validation finished. Status: {status}. Report appended to {health_report_path}.")
    except Exception as log_err:
        print(f"WARNING: Could not write to health_report.log: {log_err}")
        
    if status == "HEALTHY":
        sys.exit(0)
    else:
        sys.exit(1)
        
if __name__ == "__main__":
    run_validation()
