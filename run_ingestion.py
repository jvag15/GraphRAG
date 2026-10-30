import argparse
import os
import shutil
import traceback
import time
from dotenv import load_dotenv
from pathlib import Path
import json
from datetime import datetime

# Load env before any imports that rely on environment variables
load_dotenv()

# Silence HuggingFace hub calls — all models are local
if os.environ.get("HF_HUB_OFFLINE") == "1":
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

import torch
import gc
import subprocess
import sys
from src.ingestion.tracker import Tracker
from src.extraction.vector_embed import load_embedding_model, embed_chunks, get_chroma_collection, upsert_chunks
from src.extraction.graph_builder import load_llm, extract_and_build_graph
from src.extraction.graph_io import save_graph, load_graph
from src.extraction.keyword_index import build_bm25_index
from src.models import Chunk


class FileLock:
    """A simple cross-process file-based lock using atomic OS-level file creation."""
    def __init__(self, lock_file: str, timeout: float = 300.0, delay: float = 0.1):
        self.lock_file = Path(lock_file)
        self.timeout = timeout
        self.delay = delay
        self.is_locked = False

    def acquire(self) -> bool:
        start_time = time.time()
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                # Atomically create the lock file. Fail if it exists.
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.is_locked = True
                return True
            except FileExistsError:
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"Timeout waiting for lock on {self.lock_file}")
                time.sleep(self.delay)

    def release(self) -> None:
        if self.is_locked:
            try:
                self.lock_file.unlink(missing_ok=True)
            except Exception:
                pass
            self.is_locked = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

# OCR dependencies
try:
    import pdfplumber
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    # These will be handled at runtime; if missing, we'll fall back to original parser if available
    pdfplumber = None
    convert_from_path = None
    pytesseract = None
    OCR_AVAILABLE = False

# Try to import the original parser as fallback
try:
    from src.ingestion.parser import parse_file as original_parse_file
except ImportError:
    original_parse_file = None


def rollback_partial_ingestion(filename: str) -> None:
    """
    Rollback partial ingestion artifacts for a failed file.
    Removes embeddings from ChromaDB and nodes/edges from knowledge graph
    that are associated with the given filename.
    """
    try:
        # Rollback ChromaDB embeddings
        embed_path = os.environ.get("EMBED_MODEL_PATH", "")
        if embed_path and os.path.exists(embed_path):
            from src.extraction.vector_embed import get_chroma_collection
            chroma_path = os.environ.get("CHROMA_PATH", "data/chroma_db")
            chroma_collection = os.environ.get("CHROMA_COLLECTION", "legal_chunks")
            
            with FileLock("data/chromadb.lock"):
                collection = get_chroma_collection(chroma_path, chroma_collection)

                # Get all IDs where source metadata matches the filename
                # Note: To avoid SQL variable limits, we query for targeted source_path containing filename
                # using the $contains filter.
                results = collection.get(
                    where={"source_path": {"$contains": filename}},
                    include=["metadatas"]
                )
                ids_to_delete = results.get("ids", [])

                # Delete matching embeddings
                if ids_to_delete:
                    collection.delete(ids=ids_to_delete)
                    print(f"Rolled back {len(ids_to_delete)} embeddings for {filename} from ChromaDB")

        # Rollback knowledge graph
        graph_path = os.environ.get("GRAPH_PATH", "data/knowledge_graph.json")
        if os.path.exists(graph_path):
            import networkx as nx
            
            with FileLock("data/knowledge_graph.lock"):
                # Load existing graph
                G = nx.readwrite.json_graph.node_link_graph(json.load(open(graph_path)))

                # Find nodes to remove (those with source matching filename)
                nodes_to_remove = []
                for node_id, node_data in G.nodes(data=True):
                    source_path = node_data.get("source_path", "")
                    source = node_data.get("source", "")
                    if source == filename or source_path == filename or filename in source_path:
                        nodes_to_remove.append(node_id)

                # Find edges to remove (those where source or target node has source matching filename)
                edges_to_remove = []
                for u, v, key, edge_data in G.edges(keys=True, data=True):
                    u_source = G.nodes[u].get("source") or G.nodes[u].get("source_path") if u in G.nodes else None
                    v_source = G.nodes[v].get("source") or G.nodes[v].get("source_path") if v in G.nodes else None
                    if (u_source and filename in str(u_source)) or (v_source and filename in str(v_source)):
                        edges_to_remove.append((u, v, key))

                # Remove nodes and edges
                for node_id in nodes_to_remove:
                    G.remove_node(node_id)

                for u, v, key in edges_to_remove:
                    G.remove_edge(u, v, key)

                # Save the cleaned graph back
                if nodes_to_remove or edges_to_remove:
                    # Convert to node-link format for JSON serialization
                    data = nx.readwrite.json_graph.node_link_data(G)
                    with open(graph_path, 'w') as f:
                        json.dump(data, f, indent=2)
                    print(f"Rolled back {len(nodes_to_remove)} nodes and {len(edges_to_remove)} edges for {filename} from knowledge graph")

    except Exception as e:
        print(f"WARNING: Rollback failed for {filename}: {e}")
        # Don't raise the exception - we want to continue with the quarantine process


def parse_file(file_path: str) -> list[Chunk]:
    """
    Parse a PDF file into chunks with OCR fallback for scanned pages.

    For each page, attempts standard text extraction. If a page yields
    fewer than 20 readable words, falls back to OCR via pdf2image and pytesseract.

    Args:
        file_path: Path to the PDF file.

    Returns:
        List of Chunk objects.
    """
    # Fall back to original parser if OCR dependencies are not available
    if not OCR_AVAILABLE:
        if original_parse_file is not None:
            return original_parse_file(file_path)
        else:
            print(f"WARNING: OCR dependencies not available and no original parser found for {file_path}")
            return []

    chunks = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # First, try standard text extraction
                text = page.extract_text() or ""

                # Check if page has insufficient text (likely scanned/image-based)
                if len(text.strip().split()) < 20:
                    # Convert page to image and perform OCR
                    try:
                        images = convert_from_path(
                            file_path,
                            first_page=i+1,  # pdf2image uses 1-indexed pages
                            last_page=i+1,
                            fmt='jpeg',
                            thread_count=1
                        )
                        if images:
                            # Use pytesseract to extract text from the image
                            ocr_text = pytesseract.image_to_string(images[0], lang='eng')
                            text = ocr_text
                        else:
                            # Fallback to empty string if conversion fails
                            text = ""
                    except Exception as e:
                        print(f"WARNING: OCR failed for page {i+1} in {file_path}: {e}")
                        # Keep the original text (which was insufficient) or use empty?
                        # We'll keep the original text in case it had some content
                        pass

                # Create a chunk for this page
                chunk = Chunk(
                    chunk_id=f"{os.path.basename(file_path)}_page_{i}",
                    source_path=file_path,
                    source_type="pdf",
                    page_number=i,  # 0-indexed page number
                    section_header="",  # Not available from simple extraction
                    text=text.strip(),
                    element_type="page",
                    offset=0  # Offset within page not tracked
                )
                chunks.append(chunk)

    except Exception as e:
        print(f"ERROR: Failed to parse {file_path}: {e}")
        # Fall back to original parser if available
        if original_parse_file is not None:
            try:
                return original_parse_file(file_path)
            except Exception as e2:
                print(f"ERROR: Original parser also failed: {e2}")
                return []
        else:
            return []

    return chunks


def parse_file_worker(file_path_str: str) -> dict:
    """
    Worker function to parse a single PDF file inside a child process.
    Returns a dictionary:
    {
        "success": bool,
        "file_path": str,
        "chunks": list[Chunk],
        "error": str | None
    }
    """
    import traceback
    try:
        file_path = Path(file_path_str)
        chunks = parse_file(str(file_path))
        return {
            "success": True,
            "file_path": str(file_path),
            "chunks": chunks,
            "error": None
        }
    except Exception as e:
        tb_str = traceback.format_exc()
        return {
            "success": False,
            "file_path": file_path_str,
            "chunks": [],
            "error": tb_str
        }


# New environment variable reads for storage tiers
STAGING_DIR = Path(os.environ.get("HDD_BASE_PATH", "data/ingestion_pool")) / "staging"
ARCHIVE_DIR = Path(os.environ.get("HDD_BASE_PATH", "data/ingestion_pool")) / "archive"
QUARANTINE_DIR = Path(os.environ.get("HDD_BASE_PATH", "data/ingestion_pool")) / "quarantine"

# Extensions that are never valid PDF ingestion candidates — auto-quarantine on sight.
# These files stay in staging/ forever if not filtered, causing re-scan on every boot.
SKIP_EXTENSIONS = frozenset({
    ".error", ".log", ".tmp", ".lock",
    ".partial", ".csv", ".xlsx", ".docx",
})

# Known error substrings from pdfplumber/pdfminer that indicate a corrupt or
# non-PDF file. These trigger auto-quarantine instead of the generic exception path.
_CORRUPT_PDF_MARKERS = (
    "No /Root object!",
    "Unsupported extension",
    "PdfReadError",
    "EOF marker not found",
    "Invalid elementary object",
)


def check_and_install_requirements():
    """Check if all packages in requirements.txt are installed, install missing ones."""
    req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if not os.path.exists(req_path):
        print(f"WARNING: requirements.txt not found at {req_path}")
        return

    print("Checking requirements.txt...")
    try:
        # Get list of required packages
        with open(req_path, 'r') as f:
            required = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        # Get list of installed packages
        result = subprocess.run([sys.executable, "-m", "pip", "list", "--format=freeze"],
                              capture_output=True, text=True, check=True)
        installed_packages = {line.split('==')[0].lower() for line in result.stdout.split('\n') if '==' in line}

        # Check each required package
        missing = []
        for package in required:
            pkg_name = package.split('==')[0].split('>=')[0].split('<=')[0].strip().lower()
            if pkg_name not in installed_packages:
                missing.append(package)

        if missing:
            print(f"Missing packages: {missing}")
            print("Installing missing packages...")
            subprocess.run([sys.executable, "-m", "pip", "install"] + missing, check=True)
            print("All requirements installed.")
        else:
            print("All requirements already installed.")
    except Exception as e:
        print(f"Warning: Could not check requirements: {e}")


def preflight_check():
    """Validate all required files and config exist before starting pipeline."""
    import torch
    errors = []
    warnings = []

    # Check model files exist
    llama_path = os.environ.get("LLAMA_MODEL_PATH", "")
    embed_path = os.environ.get("EMBED_MODEL_PATH", "")

    if not os.path.exists(llama_path):
        errors.append(f"LLAMA model not found: {llama_path}")

    if not os.path.isdir(embed_path):
        errors.append(f"Embedding model directory not found: {embed_path}")

    # Check GPU
    if not torch.cuda.is_available():
        warnings.append("CUDA not available — will run on CPU (slow)")
    else:
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"GPU: {torch.cuda.get_device_name(0)} ({vram_gb:.1f}GB VRAM)")

    # Check API key (warn only — not needed for ingestion)
    if not os.environ.get("ANTHROPIC_API_KEY") or \
       os.environ.get("ANTHROPIC_API_KEY") == "placeholder":
        warnings.append("ANTHROPIC_API_KEY not set — query pipeline will not work")

    # Check ingestion directory
    ingestion_dir = os.environ.get("INGESTION_DIR", "ingestion_mouth")
    if not os.path.isdir(ingestion_dir):
        errors.append(f"Ingestion directory not found: {ingestion_dir}")

    # Check data directories
    for d in ["data/chroma_db", "data/bm25_index"]:
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            print(f"Created missing directory: {d}")

    # Print results
    for w in warnings:
        print(f"WARNING: {w}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        raise SystemExit("Preflight check failed. Fix errors above before running.")

    print("Preflight check passed.")


def run_ingestion(source: str = "local", force: bool = False):
    preflight_check()
    tracker = Tracker(os.environ["INGESTION_LOG_PATH"])
    ingestion_dir = os.environ["INGESTION_DIR"]

    if source == "sharepoint":
        if os.environ.get("SP_ENABLED", "false").lower() == "true":
            from src.ingestion.sharepoint_client import SharePointClient
            sp = SharePointClient()
            sp.download_new_files(ingestion_dir, tracker)
        else:
            print("SharePoint is disabled in .env (SP_ENABLED). Skipping SP download.")

    pending_files = tracker.get_pending(ingestion_dir)
    if not pending_files:
        print("No new files to ingest.")
        return

    print(f"Found {len(pending_files)} files to ingest.")

    # Stage 1: Parse all files into chunks
    print("\n==> Stage 1: Parsing")
    all_chunks = []
    for i, path in enumerate(pending_files, 1):
        filename = os.path.basename(path)
        print(f"[{i}/{len(pending_files)}] Parsing: {filename}")
        try:
            chunks = parse_file(path)
            all_chunks.extend(chunks)
            tracker.mark_stage(path, "chunked", chunk_count=len(chunks))
        except Exception as e:
            print(f"ERROR parsing {path}: {e}")
            tracker.mark_stage(path, "failed")
            # Rollback any partial ingestion for this file
            rollback_partial_ingestion(filename)

    print(f"Total chunks created: {len(all_chunks)}")
    if not all_chunks:
        print("No valid chunks were extracted. Aborting pipeline.")
        return

    # Stage 2: Embed chunks (embedding model loaded, then unloaded)
    print("\n==> Stage 2: Vector Embedding")
    embed_model_name = os.path.basename(os.environ["EMBED_MODEL_PATH"])
    print(f"Starting Embedding using RTX 3060 using {embed_model_name}")
    embed_model = load_embedding_model(
        os.environ["EMBED_MODEL_PATH"],
        device=os.environ.get("EMBED_DEVICE", "cuda")
    )
    collection = get_chroma_collection(os.environ["CHROMA_PATH"], os.environ["CHROMA_COLLECTION"])
    embeddings = embed_chunks(embed_model, all_chunks)
    upsert_chunks(collection, all_chunks, embeddings)

    for path in pending_files:
        tracker.mark_stage(path, "embedded")

    # CRITICAL: unload embedding model before loading Llama
    del embed_model
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        except Exception as e:
            print(f"WARNING: CUDA cache clear warning: {e}")
    print("Embedding model unloaded. VRAM freed.")

    # Stage 3: Entity extraction and graph building
    print("\n==> Stage 3: Graph Construction")
    llama_model_name = os.path.basename(os.environ["LLAMA_MODEL_PATH"])
    print(f"Starting Entity Extraction using RTX 3060 using {llama_model_name}")
    llm = load_llm(
        os.environ["LLAMA_MODEL_PATH"],
        n_gpu_layers=int(os.environ.get("LLAMA_N_GPU_LAYERS", -1))
    )

    # Load existing graph if it exists; append new nodes/edges
    graph_path = os.environ["GRAPH_PATH"]
    if Path(graph_path).exists() and not force:
        G = load_graph(graph_path)
        print(f"Loaded existing graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    else:
        import networkx as nx
        G = nx.MultiDiGraph()

    G = extract_and_build_graph(llm, all_chunks, G)
    save_graph(G, graph_path)

    for path in pending_files:
        tracker.mark_stage(path, "graph_built")

    # CRITICAL: unload Llama model before continuing
    del llm
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        except Exception as e:
            print(f"WARNING: CUDA cache clear warning: {e}")
    print("Llama unloaded. VRAM freed.")

    # Stage 4: Build/update BM25 index
    print("\n==> Stage 4: Keyword Indexing (BM25)")
    # BM25 must be rebuilt from all chunks, not just new ones (BM25Okapi is not incremental)
    # Load all previously embedded chunks from ChromaDB for full rebuild
    all_docs = collection.get(include=["documents", "metadatas"])
    from src.models import Chunk
    all_chunks_for_bm25 = [
        Chunk(
            chunk_id=cid,
            source_path=meta.get("source_path", ""),
            source_type=meta.get("source_type", ""),
            page_number=meta.get("page_number"),
            section_header=meta.get("section_header"),
            text=text,
            element_type=meta.get("element_type", ""),
            offset=meta.get("offset", 0)
        )
        for cid, text, meta in zip(
            all_docs["ids"], all_docs["documents"], all_docs["metadatas"]
        )
    ]

    if all_chunks_for_bm25:
        build_bm25_index(all_chunks_for_bm25, os.environ["BM25_INDEX_PATH"])
    else:
        print("Warning: No chunks found in ChromaDB to build BM25 index.")

    for path in pending_files:
        tracker.mark_stage(path, "complete")
        # Delete source file after successful ingestion if SHA256 matches
        current_hash = tracker.compute_sha256(path)
        record = tracker._log_data.get(current_hash)
        if record and record.get("status") == "complete":
            try:
                os.remove(path)
                print(f"Deleted: {os.path.basename(path)}")
            except OSError as e:
                print(f"Error deleting {path}: {e}")

    print("\n==> Ingestion complete.")


def process_staging_queue(target_file: str = None) -> None:
    """
    Process files in the HDD staging directory in a single, massive unified batch run.
    Extracts text from all files simultaneously, flattens them into a single global array,
    and runs them through a single progress-tracked execution pipeline.
    """
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    # Find all files in staging (including non-PDF that need quarantine)
    all_files = list(STAGING_DIR.iterdir())
    pdf_files = []
    for f in all_files:
        if f.suffix.lower() in SKIP_EXTENSIONS:
            # Auto-quarantine non-ingestible files
            try:
                shutil.move(str(f), str(QUARANTINE_DIR / f.name))
                print(f"Auto-quarantined (skip extension): {f.name}")
            except Exception as move_err:
                print(f"WARNING: Could not quarantine {f.name}: {move_err}")
            continue
        if f.suffix.lower() in (".pdf",) or f.suffix in (".PDF",):
            pdf_files.append(f)

    if not pdf_files:
        print("No PDF files found in staging directory.")
        return

    print(f"Found {len(pdf_files)} files in staging directory. Launching single unified batch run.")

    # Stage 1: Parse all files into a single unified array (concurrently)
    print("\n==> Stage 1: Unified Concurrent Parsing")
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    try:
        multiprocessing.set_start_method('fork', force=True)
    except Exception:
        # Native Linux default start method fallback if set_start_method fails or is already set
        pass

    all_chunks = []
    successfully_parsed_files = []
    failed_files = []

    # Convert Path objects to strings for child process pickling safety
    file_paths_str = [str(f) for f in pdf_files]
    max_workers = min(len(file_paths_str), multiprocessing.cpu_count())
    print(f"Starting ProcessPoolExecutor with {max_workers} CPU workers.")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(parse_file_worker, file_paths_str))

    for res in results:
        file_path = Path(res["file_path"])
        filename = file_path.name
        if res["success"]:
            chunks = res["chunks"]
            all_chunks.extend(chunks)
            successfully_parsed_files.append(file_path)
            print(f"Successfully chunked {filename} into {len(chunks)} chunks.")
        else:
            tb_str = res["error"]
            print(f"ERROR parsing {filename}: {tb_str}")
            failed_files.append((file_path, tb_str))

    print(f"Total chunks parsed across all files: {len(all_chunks)}")
    if not all_chunks:
        print("No valid chunks were extracted from staging files. Aborting pipeline.")
        # Quarantine any failed files
        for f_path, tb in failed_files:
            try:
                error_log_path = QUARANTINE_DIR / f"{f_path.name}.error.log"
                with open(error_log_path, "w") as err_f:
                    err_f.write(tb)
                shutil.move(str(f_path), str(QUARANTINE_DIR / f_path.name))
                print(f"Quarantined failed file: {f_path.name}")
            except Exception as quarantine_err:
                print(f"WARNING: Could not quarantine {f_path.name}: {quarantine_err}")
        return

    # Stage 2: Vector Embedding on all chunks
    print("\n==> Stage 2: Unified Vector Embedding")
    try:
        embed_model_name = os.path.basename(os.environ["EMBED_MODEL_PATH"])
        print(f"Starting Embedding using RTX 3060 with {embed_model_name}")
        embed_model = load_embedding_model(
            os.environ["EMBED_MODEL_PATH"],
            device=os.environ.get("EMBED_DEVICE", "cuda")
        )
        
        # Open ChromaDB collection
        collection = get_chroma_collection(os.environ["CHROMA_PATH"], os.environ["CHROMA_COLLECTION"])
        embeddings = embed_chunks(embed_model, all_chunks)
        upsert_chunks(collection, all_chunks, embeddings)
        
        # Unload embedding model
        del embed_model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("Embedding model unloaded. VRAM freed.")
    except Exception as e:
        print(f"FATAL ERROR in Stage 2 (Embedding): {e}")
        traceback.print_exc()
        # On fatal failure, quarantine all files involved in this batch
        for f_path in successfully_parsed_files:
            failed_files.append((f_path, f"Embedding failed: {e}\n{traceback.format_exc()}"))
        successfully_parsed_files.clear()
        all_chunks.clear()

    # Stage 3: Entity Extraction and Graph Building on all chunks
    if all_chunks:
        print("\n==> Stage 3: Unified Graph Construction")
        try:
            # Count files in staging to dynamically route model
            total_files = len(pdf_files)
            
            if total_files > 250:
                model_path_rel = "models/gemma-2-9b-instruct-q6_k.gguf"
                n_parallel = 4
                n_ctx = 4096
            elif total_files >= 100:
                model_path_rel = "models/llama-3.1-8b-instruct-q8_0.gguf"
                n_parallel = 2
                n_ctx = 4096
            else:
                model_path_rel = "models/mistral-nemo-12b-instruct-q5_k_m.gguf"
                n_parallel = 1
                n_ctx = 8192
                
            # Construct model path relative to project
            project_root = Path(__file__).resolve().parent
            model_path = project_root / model_path_rel
            
            if not model_path.exists():
                # Check absolute server path fallback
                server_models_dir = Path(".") / model_path_rel
                if server_models_dir.exists():
                    model_path = server_models_dir
                else:
                    print(f"WARNING: Chosen model path {model_path_rel} not found locally or at server path. Falling back to env LLAMA_MODEL_PATH.")
                    model_path = Path(os.environ.get("LLAMA_MODEL_PATH"))
                    
            # Update n_ctx in environment so load_llm receives it
            os.environ["LLAMA_N_CTX"] = str(n_ctx)
            
            # Log dynamic model routing decision
            log_msg = f"DYNAMIC ROUTING: total_files={total_files}, chosen_model={model_path_rel}, n_parallel={n_parallel}, n_ctx={n_ctx}"
            print(log_msg)
            try:
                log_dir = project_root / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                with open(log_dir / "batch_coordination.log", "a") as coord_log:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    coord_log.write(f"{timestamp} - INFO - [DYNAMIC ROUTER] {log_msg}\n")
            except Exception as log_err:
                print(f"WARNING: Could not log to batch_coordination.log: {log_err}")
                
            llama_model_name = model_path.name
            print(f"Starting Entity Extraction using RTX 3060 with {llama_model_name}")
            llm = load_llm(
                str(model_path),
                n_gpu_layers=int(os.environ.get("LLAMA_N_GPU_LAYERS", -1)),
                n_parallel=n_parallel
            )
            
            graph_path = os.environ["GRAPH_PATH"]
            if Path(graph_path).exists():
                G = load_graph(graph_path)
                print(f"Loaded existing graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
            else:
                import networkx as nx
                G = nx.MultiDiGraph()
                
            G = extract_and_build_graph(llm, all_chunks, G, n_parallel=n_parallel)
            save_graph(G, graph_path)
            
            # Unload Llama model
            del llm
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("Llama unloaded. VRAM freed.")
        except Exception as e:
            print(f"FATAL ERROR in Stage 3 (Graph Construction): {e}")
            traceback.print_exc()
            # On fatal failure, quarantine all files involved in this batch
            for f_path in successfully_parsed_files:
                failed_files.append((f_path, f"Graph construction failed: {e}\n{traceback.format_exc()}"))
            successfully_parsed_files.clear()
            all_chunks.clear()

    # Stage 4: Keyword Indexing (BM25)
    if successfully_parsed_files:
        print("\n==> Stage 4: Unified Keyword Indexing (BM25)")
        # Rebuild BM25 index from all chunks in ChromaDB
        try:
            collection = get_chroma_collection(os.environ["CHROMA_PATH"], os.environ["CHROMA_COLLECTION"])
            # Query IDs first to prevent too many SQL variables SQLite error
            all_ids = collection.get(include=[])["ids"]
            print(f"Loading {len(all_ids)} document chunks from ChromaDB for BM25 rebuild...")
            
            documents = []
            metadatas = []
            chunk_size = 2000
            for idx in range(0, len(all_ids), chunk_size):
                batch_ids = all_ids[idx:idx+chunk_size]
                batch = collection.get(ids=batch_ids, include=["documents", "metadatas"])
                documents.extend(batch.get("documents", []))
                metadatas.extend(batch.get("metadatas", []))
                
            from src.models import Chunk
            all_chunks_for_bm25 = [
                Chunk(
                    chunk_id=cid,
                    source_path=meta.get("source_path", ""),
                    source_type=meta.get("source_type", ""),
                    page_number=meta.get("page_number"),
                    section_header=meta.get("section_header"),
                    text=text,
                    element_type=meta.get("element_type", ""),
                    offset=meta.get("offset", 0)
                )
                for cid, text, meta in zip(
                    all_ids, documents, metadatas
                )
            ]
            if all_chunks_for_bm25:
                build_bm25_index(all_chunks_for_bm25, os.environ["BM25_INDEX_PATH"])
                print(f"Successfully rebuilt BM25 index with {len(all_chunks_for_bm25)} chunks.")
            else:
                print("Warning: No chunks found in ChromaDB to build BM25 index.")
        except Exception as e:
            print(f"WARNING: BM25 index rebuild failed: {e}")
            traceback.print_exc()

    # Move successfully processed files to archive
    for f_path in successfully_parsed_files:
        filename = f_path.name
        try:
            shutil.move(str(f_path), str(ARCHIVE_DIR / filename))
            print(f"Archived: {filename}")
        except Exception as archive_err:
            print(f"WARNING: Could not archive successfully processed file {filename}: {archive_err}")

    # Move failed files to quarantine
    for f_path, tb in failed_files:
        filename = f_path.name
        try:
            # Rollback any partial chunks/graph modifications for this file
            rollback_partial_ingestion(filename)
            
            error_log_path = QUARANTINE_DIR / f"{filename}.error.log"
            with open(error_log_path, 'w') as err_f:
                err_f.write(tb)
                
            if f_path.exists():
                shutil.move(str(f_path), str(QUARANTINE_DIR / filename))
                print(f"Quarantined: {filename}")
        except Exception as quarantine_err:
            print(f"WARNING: Could not quarantine failed file {filename}: {quarantine_err}")


    # Force flush VRAM to prevent PyTorch/llama.cpp context corruption
    gc.collect()
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        except Exception as e:
            print(f"WARNING: CUDA cache clear warning: {e}")
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["local", "sharepoint", "staging"], default="local")
    parser.add_argument("--force-reingest", action="store_true")
    parser.add_argument("--file", type=str, default=None, help="Target specific filename to process")
    args = parser.parse_args()

    # Check requirements before starting
    # check_and_install_requirements()

    if args.source == "staging":
        process_staging_queue(args.file)
    else:
        run_ingestion(args.source, args.force_reingest)