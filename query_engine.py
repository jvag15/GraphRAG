import os
import sys
import re
import socket
import subprocess
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is in Python path for importing internal modules
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables
load_dotenv()

# Silence HuggingFace online queries since we run fully offline
if os.environ.get("HF_HUB_OFFLINE") == "1" or os.environ.get("TRANSFORMERS_OFFLINE") == "1":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Safe imports with fallback error handling
try:
    import chromadb
    import networkx as nx
    import orjson
    import torch
    import llama_cpp
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    print(f"CRITICAL ERROR: Missing dependency: {e}")
    print("Please activate the pyenv/virtual environment or run `pip install -r requirements.txt`.")
    sys.exit(1)


SYSTEM_PROMPT_TEMPLATE = """You are an elite, literal statutory compliance auditor. Your sole task is to analyze the provided Context (retrieved database text chunks and knowledge graph subgraphs) and output a highly factual compliance answer matching the user's query.

You must execute token generation strictly under these three structural laws:

1. COMPLIANCE GROUNDING (DO NOT INVENT NUMBERS)
- Rely exclusively on facts stated explicitly inside the Context payload.
- If the context does not provide a specific mathematical calculation or exact asset valuation example for the scenario, explain the interplay of the relevant Accounting Standards qualitatively.
- It is strictly forbidden to manufacture example numbers, fabricate domestic loan interest rates, or invent arbitrary asset calculations out of thin air. If it is not written verbatim in the context, do not write it in the output.

2. EXECUTIVE FORMATTING (START DIRECTLY WITH THE ANSWER)
- Output only the clean, final markdown response.
- Start streaming text directly with the core answer data. 
- It is strictly forbidden to include internal reasoning logs, formatting chain-of-thought blocks, scratchpad summaries, planning notes, translation disclaimers, or drafting iterations. 
- To prevent recursive attention loops, proceed lineally through your answer sections. Do not repeat terms, bullet conditions, or introductory phrases redundantly.

3. INLINE CITATION ANCHORING
- Maintain the system's exact inline citation template layer. 
- Place the raw hexadecimal document source chunk ID tokens (for example, [01a8f94847a6c3af]) immediately following the sentence or specific clause they validate.

Context passages:
{context}
"""


def check_port_in_use(port: int) -> bool:
    """Check if a local port is bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def perform_port_kill():
    """Kill active processes on port 8000 and 8080 to prevent CUDA OOM."""
    print("Executing port sanitation to clear query and inference servers...")
    for port in [8000, 8080]:
        if check_port_in_use(port):
            try:
                print(f"Port {port} is active. Force terminating process...")
                subprocess.run(["sudo", "fuser", "-k", f"{port}/tcp"], check=False, capture_output=True)
            except Exception as e:
                print(f"Failed to clear port {port} using fuser: {e}")
    
    # Process name sweeps
    try:
        subprocess.run(["pkill", "-9", "-f", "llama_cpp.server"], check=False, capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "llama_cpp server"], check=False, capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "uvicorn src.api.fastapi_service"], check=False, capture_output=True)
        print("Successfully sent SIGKILL to ghost LLM/API processes.")
    except Exception as e:
        print(f"Error executing pkill sweeps: {e}")


def get_model_path_from_env() -> str:
    """Find a valid model path configured in env or locally."""
    # 1. Qwen model path (Preferred query time model)
    qwen = os.environ.get("QWEN_MODEL_PATH")
    if qwen:
        # Check relative or absolute path
        p = Path(qwen)
        if p.exists():
            return str(p)
        # Try relative to project root if it was specified as an absolute server path
        rel_p = PROJECT_ROOT / p.name
        if rel_p.exists():
            return str(rel_p)
            
    # 2. Llama model path
    llama = os.environ.get("LLAMA_MODEL_PATH")
    if llama:
        p = Path(llama)
        if p.exists():
            return str(p)
        # Check standard server path backup
        fallback_llama = Path("models/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf")
        if fallback_llama.exists():
            return str(fallback_llama)
            
    # 3. Direct directory search
    models_dir = PROJECT_ROOT / "models"
    if models_dir.exists():
        candidates = list(models_dir.glob("*.gguf"))
        if candidates:
            # Sort to prefer Qwen, then Llama, then others
            qwen_candidates = [c for c in candidates if "qwen" in c.name.lower()]
            if qwen_candidates:
                return str(qwen_candidates[0])
            llama_candidates = [c for c in candidates if "llama" in c.name.lower()]
            if llama_candidates:
                return str(llama_candidates[0])
            return str(candidates[0])
            
    raise FileNotFoundError("Could not locate any valid .gguf model file. Configure LLAMA_MODEL_PATH or QWEN_MODEL_PATH.")


def load_bge_embedding(model_path: str, device: str = "cuda") -> SentenceTransformer:
    """Initialize BGE embedding model."""
    if device == "cuda":
        if not torch.cuda.is_available():
            print("WARNING: CUDA requested but not available. Falling back to CPU.")
            device = "cpu"
        else:
            try:
                free_mem, total_mem = torch.cuda.mem_get_info(0)
                free_gib = free_mem / (1024 ** 3)
                if free_gib < 1.5:
                    print(f"WARNING: Low VRAM ({free_gib:.2f} GiB available). Loading embedding model on CPU to avoid OOM.")
                    device = "cpu"
            except Exception:
                pass
    
    print(f"Loading embedding model from: {model_path} on {device}...")
    model = SentenceTransformer(model_path, trust_remote_code=True, device=device)
    return model


def embed_query(model: SentenceTransformer, query: str) -> list[float]:
    """Encode user query following BGE large prefix rules."""
    prefix = "Represent this sentence for searching relevant passages: "
    embeddings = model.encode(
        [f"{prefix}{query}"],
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True
    )
    return embeddings[0].tolist()


# Global cache for the inverted index to allow O(1) lookups
_CHUNK_TO_ENTITIES_INDEX = None

def _build_chunk_to_entities_index(G: nx.MultiDiGraph) -> dict:
    """Build an inverted index mapping chunk_id to a list of entity node_ids in O(N)."""
    index = {}
    for node_id, node_data in G.nodes(data=True):
        chunk_id = node_data.get("source_chunk_id")
        if chunk_id:
            if chunk_id not in index:
                index[chunk_id] = []
            index[chunk_id].append(node_id)
    return index

def get_entities_for_chunks(G: nx.MultiDiGraph, chunk_ids: list[str]) -> list[str]:
    """Retrieve graph entity node IDs whose source_chunk_id matches chunk IDs in O(1)."""
    global _CHUNK_TO_ENTITIES_INDEX
    if _CHUNK_TO_ENTITIES_INDEX is None:
        _CHUNK_TO_ENTITIES_INDEX = _build_chunk_to_entities_index(G)
        
    entity_ids = []
    for chunk_id in chunk_ids:
        if chunk_id in _CHUNK_TO_ENTITIES_INDEX:
            entity_ids.extend(_CHUNK_TO_ENTITIES_INDEX[chunk_id])
            
    return list(set(entity_ids))


def extract_2hop_subgraph(G: nx.MultiDiGraph, seed_nodes: list[str], max_edges: int = 50) -> list[str]:
    """
    Perform Breadth-First Search (BFS) traversal up to 2-hops from seed nodes.
    Compiles relationships into clean text representations.
    """
    if not seed_nodes:
        return []
        
    # Resolve seeds that are actually in the graph
    valid_seeds = [n for n in seed_nodes if n in G]
    if not valid_seeds:
        return []
        
    hop1_nodes = set()
    hop2_nodes = set()
    
    for seed in valid_seeds:
        # Get 1-hop neighborhood
        ego1 = nx.ego_graph(G, seed, radius=1, undirected=True)
        hop1_nodes.update(ego1.nodes())
        
        # Get 2-hop neighborhood
        ego2 = nx.ego_graph(G, seed, radius=2, undirected=True)
        hop2_nodes.update(ego2.nodes())
        
    # Compile relation edges into descriptive sentences
    relationship_strings = []
    seen_edges = set()
    
    # Prioritization queue: start with seeds, then 1-hop, then 2-hop nodes
    priority_nodes = list(valid_seeds) + list(hop1_nodes - set(valid_seeds)) + list(hop2_nodes - hop1_nodes - set(valid_seeds))
    
    for u in priority_nodes:
        if len(relationship_strings) >= max_edges:
            break
        if u not in G:
            continue
            
        u_label = G.nodes[u].get("label", u)
        u_type = G.nodes[u].get("type", "Unknown")
        
        for v in G.successors(u):
            if v in visited:
                edge_dict = G.get_edge_data(u, v)
                if not edge_dict:
                    continue
                for key, edge_data in edge_dict.items():
                    edge_id = (u, v, key)
                    if edge_id not in seen_edges:
                        seen_edges.add(edge_id)
                        v_label = G.nodes[v].get("label", v)
                        v_type = G.nodes[v].get("type", "Unknown")
                        relation = edge_data.get("relation", "related to")
                        evidence = edge_data.get("evidence", "").strip()
                        
                        rel_str = f"Entity '{u_label}' ({u_type}) --[{relation}]--> Entity '{v_label}' ({v_type})"
                        if evidence:
                            # Clean/format evidence text
                            clean_evidence = re.sub(r'\s+', ' ', evidence)
                            if len(clean_evidence) > 150:
                                clean_evidence = clean_evidence[:147] + "..."
                            rel_str += f" | Evidence: \"{clean_evidence}\""
                        
                        relationship_strings.append(rel_str)
                        if len(relationship_strings) >= max_edges:
                            break
                            
    return relationship_strings


def main():
    parser = argparse.ArgumentParser(description="Hybrid GraphRAG Retrieval and Context Synthesis Engine")
    parser.add_argument("--query", type=str, required=True, help="User query to search the knowledge base")
    parser.add_argument("--top_k", type=int, default=5, help="Number of text chunks to retrieve from ChromaDB")
    parser.add_argument("--hops", type=int, default=2, help="Graph hop retrieval depth (defaults to 2-hop)")
    parser.add_argument("--max_edges", type=int, default=50, help="Maximum number of subgraph relationship strings to output")
    parser.add_argument("--model", type=str, default=None, help="Explicit path to GGUF model binary")
    parser.add_argument("--gpu_layers", type=int, default=-1, help="Number of LLM layers to offload to GPU (-1 for all)")
    parser.add_argument("--device", type=str, default="cuda", help="Device for BGE embedding model (cuda or cpu)")
    parser.add_argument("--kill-ports", action="store_true", help="Force terminate active servers on ports 8000/8080 first")
    
    args = parser.parse_args()

    # Port sanitation and verification
    if args.kill_ports:
        perform_port_kill()
    else:
        # Standard safety checks
        conflict_detected = False
        for port in [8000, 8080]:
            if check_port_in_use(port):
                print(f"WARNING: Port {port} is currently in use. Concurrent model loading will likely trigger a CUDA OOM crash!")
                conflict_detected = True
        if conflict_detected:
            if not sys.stdin.isatty():
                print("Non-interactive session detected. Proceeding without port sanitation. Watch memory/VRAM closely.")
            else:
                try:
                    ans = input("Would you like to kill active server processes on ports 8000 and 8080? (y/n): ")
                    if ans.lower().strip() == 'y':
                        perform_port_kill()
                    else:
                        print("Proceeding without port sanitation. Watch memory carefully.")
                except Exception:
                    print("Could not prompt for input. Proceeding without port sanitation.")

    # Locate Paths
    chroma_path = os.environ.get("CHROMA_PATH", "data/chroma_db")
    chroma_collection = os.environ.get("CHROMA_COLLECTION", "legal_chunks")
    graph_path = os.environ.get("GRAPH_PATH", "data/knowledge_graph.json")
    embed_model_path = os.environ.get("EMBED_MODEL_PATH", "models/bge-large-en-v1.5")
    
    # -------------------------------------------------------------
    # STAGE 1: HYPER-TARGETED VECTOR SEARCH (ChromaDB)
    # -------------------------------------------------------------
    print("\n--- STAGE 1: VECTOR RETRIEVAL ---")
    try:
        # Load embedding model
        model = load_bge_embedding(embed_model_path, device=args.device)
        query_vector = embed_query(model, args.query)
        
        # Connect to ChromaDB
        print(f"Connecting to ChromaDB client at: {chroma_path}...")
        chroma_client = chromadb.PersistentClient(path=chroma_path)
        collection = chroma_client.get_collection(name=chroma_collection)
        
        print(f"Querying collection '{chroma_collection}' for top {args.top_k} nearest chunks...")
        vector_results = collection.query(
            query_embeddings=[query_vector],
            n_results=args.top_k,
            include=["documents", "metadatas", "distances"]
        )
    except Exception as e:
        print(f"CRITICAL ERROR in Stage 1: {e}")
        sys.exit(1)
        
    # Process text chunks and build mappings
    retrieved_chunks = []
    retrieved_chunk_ids = []
    document_mappings = []
    
    if vector_results and "ids" in vector_results and len(vector_results["ids"]) > 0:
        ids = vector_results["ids"][0]
        docs = vector_results["documents"][0]
        metadatas = vector_results["metadatas"][0]
        distances = vector_results["distances"][0]
        
        for idx in range(len(ids)):
            chunk_id = ids[idx]
            text = docs[idx]
            meta = metadatas[idx] or {}
            score = 1.0 - distances[idx] # convert cosine distance to similarity
            
            retrieved_chunk_ids.append(chunk_id)
            retrieved_chunks.append({
                "chunk_id": chunk_id,
                "text": text,
                "score": score,
                "metadata": meta
            })
            
            # Record document mapping description
            doc_name = os.path.basename(meta.get("source_path", "unknown_document"))
            page_info = f"page {meta.get('page_number')}" if meta.get('page_number', -1) != -1 else "unknown page"
            header = meta.get("section_header", "")
            header_str = f" ({header})" if header else ""
            document_mappings.append(f"Chunk [{chunk_id}]: {doc_name} | {page_info}{header_str}")
            
    print(f"Successfully retrieved {len(retrieved_chunks)} text chunks.")
    for chunk in retrieved_chunks:
        doc_name = os.path.basename(chunk["metadata"].get("source_path", "unknown"))
        print(f" - [{chunk['chunk_id']}] Similarity: {chunk['score']:.4f} | Source: {doc_name}")

    # -------------------------------------------------------------
    # STAGE 2: 2-HOP SUBGRAPH EXTRACTION (NetworkX)
    # -------------------------------------------------------------
    print("\n--- STAGE 2: SUBGRAPH TRAVERSAL ---")
    try:
        print(f"Loading global knowledge graph from: {graph_path}...")
        if not Path(graph_path).exists():
            raise FileNotFoundError(f"Knowledge graph file not found at {graph_path}")
            
        with open(graph_path, "rb") as f:
            graph_data = orjson.loads(f.read())
        G = nx.node_link_graph(graph_data, directed=True, multigraph=True)
        print(f"Graph loaded successfully. Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")
        
        # Discover seed nodes associated with the retrieved chunk IDs
        print("Discovering entity seed nodes associated with retrieved chunks...")
        seed_nodes = get_entities_for_chunks(G, retrieved_chunk_ids)
        
        # Print matching seed nodes
        if seed_nodes:
            print(f"Found {len(seed_nodes)} seed entity node(s) directly bound to retrieved text chunks:")
            for seed in seed_nodes[:10]:
                label = G.nodes[seed].get("label", seed)
                ntype = G.nodes[seed].get("type", "Unknown")
                print(f" - Node: '{label}' ({ntype}) [ID: {seed}]")
            if len(seed_nodes) > 10:
                print(f" ... and {len(seed_nodes) - 10} more.")
        else:
            print("No entity nodes match the retrieved chunk IDs directly. Scanning query text for entity matches...")
            # Fallback fuzzy matching: find nodes whose label is contained in the query
            for node_id, node_data in G.nodes(data=True):
                label = node_data.get("label", "")
                if label and len(label) > 3 and label.lower() in args.query.lower():
                    seed_nodes.append(node_id)
            
            if seed_nodes:
                print(f"Fuzzy query scan discovered {len(seed_nodes)} seed node(s):")
                for seed in seed_nodes[:5]:
                    print(f" - Fuzzy Node: '{G.nodes[seed].get('label')}' [ID: {seed}]")
            else:
                print("No seed entities found in query or chunks.")
                
        # Traversal and string generation
        print(f"Extracting surrounding context up to {args.hops}-hops...")
        subgraph_strings = extract_2hop_subgraph(G, seed_nodes, max_edges=args.max_edges)
        print(f"Extracted {len(subgraph_strings)} structural relationship statements.")
        
        # Print a sample of extracted relationships
        for r_str in subgraph_strings[:5]:
            print(f" * {r_str}")
        if len(subgraph_strings) > 5:
            print(f" ... and {len(subgraph_strings) - 5} more relationships.")
            
    except Exception as e:
        print(f"ERROR in Stage 2: {e}")
        print("HINT: Proceeding with empty structural knowledge graph context.")
        subgraph_strings = []

    # -------------------------------------------------------------
    # STAGE 3: CONTEXT ASSEMBLY & LLM SYNTHESIS
    # -------------------------------------------------------------
    print("\n--- STAGE 3: LLM CONTEXT SYNTHESIS ---")
    
    # 1. Format Vector Passages
    vector_passages_text = []
    for chunk in retrieved_chunks:
        meta = chunk["metadata"]
        doc_name = os.path.basename(meta.get("source_path", "unknown"))
        page_num = meta.get("page_number", -1)
        header = meta.get("section_header", "")
        loc = f"Document: {doc_name}"
        if page_num != -1:
            loc += f", Page: {page_num}"
        if header:
            loc += f", Section: {header}"
            
        vector_passages_text.append(
            f"--- START CHUNK [{chunk['chunk_id']}] ({loc}) ---\n"
            f"{chunk['text'].strip()}\n"
            f"--- END CHUNK [{chunk['chunk_id']}] ---"
        )
    
    vector_text_context = "\n\n".join(vector_passages_text)
    
    # 2. Format Graph Subgraph Context
    if subgraph_strings:
        graph_context = "\n".join(subgraph_strings)
    else:
        graph_context = "No direct structural knowledge graph relations found for matching entities."
        
    # Assemble full context block
    full_context_block = f"""VECTOR TEXT CONTEXT:
{vector_text_context}

STRUCTURAL KNOWLEDGE GRAPH CONTEXT:
{graph_context}"""

    # Populate prompt template
    complete_prompt = SYSTEM_PROMPT_TEMPLATE.replace("{context}", full_context_block)
    
    # Find model path
    try:
        model_path = args.model if args.model else get_model_path_from_env()
    except Exception as e:
        print(f"CRITICAL ERROR in Stage 3: {e}")
        sys.exit(1)
        
    # Free up memory before loading heavy GGUF binary
    gc_collected = 0
    if 'model' in locals():
        del model
        gc_collected = 1
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if gc_collected:
        import gc
        gc.collect()

    # Load in-process llama_cpp instance
    try:
        n_threads = int(os.environ.get("LLAMA_N_THREADS", 8))
        
        # VRAM check and fallback protection
        gpu_layers = args.gpu_layers
        if gpu_layers != 0 and torch.cuda.is_available():
            try:
                free_mem, total_mem = torch.cuda.mem_get_info(0)
                free_gib = free_mem / (1024 ** 3)
                total_gib = total_mem / (1024 ** 3)
                print(f"GPU VRAM Status: {free_gib:.2f} GiB free of {total_gib:.2f} GiB total.")
                
                # Estimate requirements: Llama 8B Q8 needs ~8.5 GiB, Qwen 12B Q4 needs ~7.0 GiB
                is_q8 = "q8" in model_path.lower()
                required_gib = 8.5 if is_q8 else 7.0
                
                if free_gib < required_gib:
                    print(f"WARNING: Insufficient free VRAM ({free_gib:.2f} GiB available, {required_gib:.2f} GiB estimated required).")
                    print("To prevent CUDA OOM crash and avoid disrupting the active ingestion pipeline, offloading LLM to CPU (gpu_layers=0).")
                    gpu_layers = 0
            except Exception as vram_err:
                print(f"Warning: Could not query GPU memory: {vram_err}")
                
        print(f"Initializing in-process llama.cpp LLM: {model_path}")
        print(f"Parameters: n_ctx=4096, n_gpu_layers={gpu_layers}, n_threads={n_threads}")
        
        llm = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=4096,
            n_threads=n_threads,
            n_threads_batch=n_threads,
            n_batch=512,
            n_gpu_layers=gpu_layers,
            verbose=False
        )
        
        print("LLM loaded. Executing chat completion...")
        
        messages = [
            {"role": "system", "content": complete_prompt},
            {"role": "user", "content": args.query}
        ]
        
        response = llm.create_chat_completion(
            messages=messages,
            max_tokens=2048,
            temperature=0.1  # deterministic answers
        )
        
        generated_answer = response["choices"][0]["message"]["content"].strip()
        
        print("\n================================== FINAL GENERATED RESPONSE ==================================\n")
        print(generated_answer)
        print("\n==============================================================================================\n")
        
        # Display document mappings used for retrieval
        print("DOCUMENT SOURCES RETRIEVED:")
        for mapping in document_mappings:
            print(f" - {mapping}")
            
    except Exception as e:
        print(f"CRITICAL ERROR in Stage 3 (LLM generation): {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
