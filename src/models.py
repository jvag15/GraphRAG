# src/models.py

from dataclasses import dataclass, field
from typing import Optional, List
from pydantic import BaseModel


@dataclass
class Chunk:
    """
    The atomic unit of the ingestion pipeline.
    Every other module consumes or produces these.
    """
    chunk_id: str             # sha256(source_path + str(offset))[:16]
    source_path: str          # absolute path to the original file
    source_type: str          # "pdf" | "docx" | "xlsx" | "html" | "txt" | "csv"
    page_number: Optional[int]
    section_header: Optional[str]   # nearest preceding Title element
    text: str                 # clean text content, max ~512 tokens
    element_type: str         # unstructured element type: "NarrativeText" | "Table" | "Title" | "ListItem"
    offset: int               # position index within source file
    metadata: dict = field(default_factory=dict)


# --- Knowledge Graph Node/Edge types ---

VALID_NODE_TYPES = {
    "Act", "Section", "SubSection", "Clause", "Rule",
    "Notification", "Circular", "Definition", "Exception",
    "Form", "Penalty", "PenalCode"
}

VALID_EDGE_TYPES = {
    "AMENDED_BY",          # (Section A) --[AMENDED_BY]--> (Notification B)
    "EXCEPTION_TO",        # (Clause C) --[EXCEPTION_TO]--> (Section A)
    "DEFINITION_OF",       # (Definition D) --[DEFINITION_OF]--> (Term T)
    "APPLIES_TO",          # (Definition D) --[APPLIES_TO]--> (Clause C)
    "REFERS_TO",           # (Section X) --[REFERS_TO]--> (Section Y)
    "SUBJECT_TO",          # (Rule R) --[SUBJECT_TO]--> (Section S)
    "OVERRIDES",           # (Notification N) --[OVERRIDES]--> (Circular C)
    "EXPLAINED_BY",        # (Section S) --[EXPLAINED_BY]--> (Circular C)
    "PENALTY_UNDER",       # (Penalty P) --[PENALTY_UNDER]--> (Section S)
    "NOTIFIED_UNDER",      # (Rule R) --[NOTIFIED_UNDER]--> (Act A)
    "CROSS_REFERENCED_BY", # (Section A) --[CROSS_REFERENCED_BY]--> (Section B)
}


# --- Query Analysis Dataclass (for query router) ---

@dataclass
class QueryAnalysis:
    original_query: str
    intent: str                    # "definition" | "exception" | "procedure" | "penalty" | "amendment" | "general"
    legal_entities: List[str]      # ["Section 17", "CGST Act", "ITC", "Section 17(5)"]
    graph_seed_labels: List[str]   # same entities formatted for graph node matching
    expanded_queries: List[str]    # 2-3 rephrased versions for better recall
    requires_multi_hop: bool       # True if query spans multiple sections/acts
    hop_depth: int                 # 2 for simple, 3 for complex multi-act queries


# --- API models ---

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    top_k: int = 10
    graph_hops: int = 2


class ClearSessionRequest(BaseModel):
    session_id: str


class QueryResponse(BaseModel):
    answer: str
    sources: list['SourceReference']
    session_id: str
    has_sufficient_context: bool
    query_analysis: Optional[dict] = None  # Optional debug info (router output)


class CitedSource(BaseModel):
    chunk_id: str
    source_path: str
    section_header: Optional[str]
    text: str
    retrieval_method: str       # "vector" | "graph" | "bm25"
    relevance_score: float


# --- Retrieval Models ---

@dataclass
class RankedResult:
    chunk_id: str
    text: str
    source_path: str
    section_header: Optional[str]
    retrieval_method: str
    score: float
    reranker_score: float = 0.0  # NEW — cross-encoder reranker score (sigmoid 0-1)


@dataclass
class SearchResults:
    ranked_chunks: List[RankedResult]
    graph_path: Optional[List[str]] = None
    strategy_used: str = ""
    has_sufficient_context: bool = True    # NEW — False triggers "no data" response
    query_analysis: Optional[QueryAnalysis] = None  # NEW — router output for debugging


# --- Source Reference for API response ---

class SourceReference(BaseModel):
    chunk_id: str
    document_name: str       # filename without path, e.g. "CGST_Act_2017.pdf"
    section_header: Optional[str]
    retrieval_method: str    # "vector" | "graph" | "bm25"
    relevance_score: float   # reranker sigmoid score 0-1