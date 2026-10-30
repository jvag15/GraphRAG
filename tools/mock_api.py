"""
Mock API Server for GraphRAG GUI Testing
Provides a lightweight FastAPI endpoint that simulates the real backend.
"""

import asyncio
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any
import uvicorn

app = FastAPI(title="GraphRAG Mock API")


class QueryRequest(BaseModel):
    query: str


class Source(BaseModel):
    text: str
    metadata: Dict[str, Any]


class GraphNode(BaseModel):
    id: str
    label: str
    title: str = ""  # Optional, but we'll include for compatibility


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    graph_nodes: List[GraphNode]
    # Note: In the real API, there might be more fields, but we stick to the ones the GUI uses.


@app.post("/query", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest):
    """
    Mock endpoint that simulates processing delay and returns static data.
    """
    # Simulate network latency (2 seconds)
    await asyncio.sleep(2)

    # Hardcoded response matching the expected schema
    return QueryResponse(
        answer="This is a mock answer for testing the GUI. The real answer would come from the LLM after ingesting documents.",
        sources=[
            Source(
                text="This is a sample text chunk from a document. It demonstrates how source citations appear in the bottom-right panel.",
                metadata={
                    "source": "sample_document.pdf",
                    "section_header": "Introduction",
                    "page_number": 1
                }
            ),
            Source(
                text="Another example source showing different metadata. This helps verify the UI handles multiple sources correctly.",
                metadata={
                    "source": "another_doc.pdf",
                    "section_header": "Methodology",
                    "page_number": 5
                }
            )
        ],
        graph_nodes=[
            GraphNode(id="node1", label="AS 1", title="Accounting Standard"),
            GraphNode(id="node2", label="Revenue Recognition", title="Concept"),
            GraphNode(id="node3", label="IFRS 15", title="Reporting Standard"),
            GraphNode(id="node4", label="Contract", title="Entity"),
            GraphNode(id="node5", label="Performance Obligation", title="Concept")
        ]
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)