import os
import json
import re
import networkx as nx
import orjson
import torch
from tqdm import tqdm
from llama_cpp import Llama
from src.models import Chunk, VALID_NODE_TYPES, VALID_EDGE_TYPES


EXTRACTION_PROMPT = """/no_think
You are a legal entity and relation extractor for Indian tax and company law.

Given the following text from a legal document, extract all entities and relationships.

OUTPUT ONLY a valid JSON object. No preamble, no explanation, no markdown fences.

Schema:
{
  "entities": [{"id": "short_snake_case_id", "type": "NODETYPE", "label": "exact text from document"}],
  "relations": [{"source": "entity_id", "target": "entity_id", "type": "EDGETYPE", "evidence": "verbatim phrase max 100 chars"}]
}

Valid NODETYPE values: Act, Section, SubSection, Clause, Rule, Notification, Circular, Definition, Exception, Form, Penalty, PenalCode

Valid EDGETYPE values: AMENDED_BY, EXCEPTION_TO, DEFINITION_OF, APPLIES_TO, REFERS_TO, SUBJECT_TO, OVERRIDES, EXPLAINED_BY, PENALTY_UNDER, NOTIFIED_UNDER, CROSS_REFERENCED_BY

Edge direction rules:
- AMENDED_BY: older_rule --[AMENDED_BY]--> amending_document
- EXCEPTION_TO: exception_clause --[EXCEPTION_TO]--> rule_it_overrides
- APPLIES_TO: definition_or_rule --[APPLIES_TO]--> target_section
- SUBJECT_TO: dependent_rule --[SUBJECT_TO]--> governing_section

If no entities or relations are found, return: {"entities": [], "relations": []}

Text:
{chunk_text}"""


def _extract_json_from_text(text: str) -> dict:
    """
    Extract JSON object from text that may contain extra content.
    Looks for the first valid JSON object in the text.
    """
    # Try to parse the entire text as JSON first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Look for JSON object patterns - find content between matching braces
    # This handles cases where there's extra text before/after the JSON
    json_pattern = r'\{(?:[^{}]|(?R))*\}'

    # Since Python's re doesn't support recursive patterns, we'll use a simpler approach
    # Find the first '{' and try to parse from there, balancing braces
    start_idx = text.find('{')
    if start_idx == -1:
        return None

    brace_count = 0
    for i in range(start_idx, len(text)):
        char = text[i]
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                # Found a complete JSON object
                json_str = text[start_idx:i+1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    # If this isn't valid JSON, continue looking
                    pass

    # If we didn't find a valid JSON object with balanced braces,
    # try to find any content that looks like it could be JSON
    # Look for patterns like {"entities": [...]}
    json_like_pattern = r'\{[^}]+\}'
    matches = re.findall(json_like_pattern, text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    return None


def load_llm(model_path: str, n_gpu_layers: int = -1, n_parallel: int = 1) -> Llama:
    n_threads = int(os.environ.get("LLAMA_N_THREADS", 8))
    n_threads_batch = int(os.environ.get("LLAMA_N_THREADS_BATCH", 8))
    n_ctx = int(os.environ.get("LLAMA_N_CTX", 4096))

    llm = Llama(
        model_path=model_path,
        n_gpu_layers=n_gpu_layers,
        n_ctx=n_ctx,
        n_batch=512,
        n_threads=n_threads,
        n_threads_batch=n_threads_batch,
        verbose=True,
        n_parallel=n_parallel
    )

    print(f"LLM loaded. Threads: {n_threads}, n_ctx: {n_ctx}, n_parallel: {n_parallel}. Check stderr for 'llm_load_tensors' GPU confirmation.")
    return llm


def extract_and_build_graph(llm: Llama, chunks: list[Chunk], G: nx.MultiDiGraph = None, n_parallel: int = 1) -> nx.MultiDiGraph:
    if G is None:
        G = nx.MultiDiGraph()

    from concurrent.futures import ThreadPoolExecutor

    def process_chunk(args_tuple):
        idx, chunk = args_tuple
        slot_id = idx % n_parallel
        prompt = f"<!-- Slot {slot_id} -->\n" + EXTRACTION_PROMPT.replace("{chunk_text}", chunk.text[:2000])

        try:
            response = llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.0
            )
            raw = response["choices"][0]["message"]["content"].strip()
            data = _extract_json_from_text(raw)
            return chunk, data, raw
        except Exception as e:
            print(f"ERROR: Exception during LLM extraction for chunk {chunk.chunk_id}: {e}")
            return chunk, None, ""

    if n_parallel > 1:
        print(f"Running graph builder concurrency: {n_parallel} parallel slots.")
        with ThreadPoolExecutor(max_workers=n_parallel) as executor:
            tasks = list(enumerate(chunks))
            results = list(tqdm(
                executor.map(process_chunk, tasks),
                total=len(chunks),
                desc="Building knowledge graph (parallel slots)"
            ))
    else:
        results = []
        for idx, chunk in enumerate(tqdm(chunks, desc="Building knowledge graph (sequential)")):
            results.append(process_chunk((idx, chunk)))

    # Sequential NetworkX serialization on the main thread for safety
    for chunk, data, raw in results:
        if data is None:
            if raw:
                # Log what we got for debugging (first 200 chars)
                preview = raw[:200] + ("..." if len(raw) > 200 else "")
                print(f"WARNING: Could not parse LLM output for chunk {chunk.chunk_id}. "
                      f"Preview: {preview}")
            continue

        for entity in data.get("entities", []):
            if not isinstance(entity, dict):
                continue
            if "type" not in entity or "id" not in entity or "label" not in entity:
                continue
            if entity["type"] not in VALID_NODE_TYPES:
                continue
            node_id = f"{chunk.chunk_id}::{entity['id']}"
            G.add_node(
                node_id,
                type=entity["type"],
                label=entity["label"],
                source_chunk_id=chunk.chunk_id,
                source_path=chunk.source_path,
                section_header=chunk.section_header or ""
            )

        for rel in data.get("relations", []):
            if not isinstance(rel, dict):
                continue
            if "source" not in rel or "target" not in rel or "type" not in rel:
                continue
            if rel["type"] not in VALID_EDGE_TYPES:
                continue
            src = f"{chunk.chunk_id}::{rel['source']}"
            tgt = f"{chunk.chunk_id}::{rel['target']}"
            if src not in G or tgt not in G:
                continue
            G.add_edge(
                src, tgt,
                relation=rel["type"],
                evidence=rel.get("evidence", ""),
                source_chunk_id=chunk.chunk_id,
                confidence=1.0
            )

    return G


from src.extraction.graph_io import save_graph, load_graph