# src/retrieval/query_router.py
"""
Use Qwen3.6 to analyse the auditor's query and extract structured retrieval guidance.
"""

import json
import re
import os
from typing import List
from llama_cpp import Llama
from src.models import QueryAnalysis


def strip_thinking(text: str) -> str:
    """Remove Qwen3 ``` blocks from output."""
    return re.sub(r'```.*?```', '', text, flags=re.DOTALL).strip()


class QueryRouter:
    def __init__(self, model_path: str = None, llama: Llama = None):
        n_threads = int(os.environ.get("LLAMA_N_THREADS", 8))
        n_threads_batch = int(os.environ.get("LLAMA_N_THREADS_BATCH", 8))

        if llama is not None:
            self.llm = llama
            print(f"Query router using shared Qwen instance. Threads: {n_threads}")
        else:
            if model_path is None:
                raise ValueError("Either model_path or llama must be provided")
            self.llm = Llama(
                model_path=model_path,
                n_gpu_layers=int(os.environ.get("QWEN_N_GPU_LAYERS", -1)),
                n_ctx=int(os.environ.get("QWEN_N_CTX", 8192)),
                n_batch=int(os.environ.get("QWEN_N_BATCH", 512)),
                n_threads=n_threads,
                n_threads_batch=n_threads_batch,
                verbose=False  # Critical: verbose=False for query server
            )
            print(f"Query router Qwen loaded. Threads: {n_threads}")

    def analyse(self, query: str, conversation_summary: str = "No prior conversation.") -> QueryAnalysis:
        """Analyse query using Qwen3 in thinking mode (MODE A)."""

        # Router prompt - MODE A: thinking enabled
        prompt = f"""You are a legal query analyser for Indian CA and tax law.
Given an auditor's query, extract structured retrieval guidance.
OUTPUT ONLY valid JSON matching this exact schema, no other text:
{{
  "intent": "definition|exception|procedure|penalty|amendment|general",
  "legal_entities": ["list of section numbers, act names, defined terms found in query"],
  "graph_seed_labels": ["same entities formatted as they appear in legal text"],
  "expanded_queries": ["2-3 alternative phrasings of the query for better recall"],
  "requires_multi_hop": true/false,
  "hop_depth": 2
}}

Intent classification rules:
- definition: query asks what something means
- exception: query asks about exclusions, carve-outs, provisos
- procedure: query asks how to do something, filing, compliance steps
- penalty: query asks about fines, prosecution, consequences
- amendment: query asks about changes to existing provisions
- general: anything else

Query: {query}

Conversation context (use this to understand follow-up questions):
{conversation_summary}
"""

        try:
            response = self.llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.3  # Slight creativity for query expansion
            )

            raw = response["choices"][0]["message"]["content"].strip()

            # Strip thinking blocks
            cleaned = strip_thinking(raw)

            # Try to parse JSON
            try:
                data = json.loads(cleaned)
                return QueryAnalysis(
                    original_query=query,
                    intent=data.get("intent", "general"),
                    legal_entities=data.get("legal_entities", []),
                    graph_seed_labels=data.get("graph_seed_labels", []),
                    expanded_queries=data.get("expanded_queries", []),
                    requires_multi_hop=bool(data.get("requires_multi_hop", False)),
                    hop_depth=int(data.get("hop_depth", 2))
                )
            except json.JSONDecodeError:
                # If JSON malformed, retry once with stricter prompt
                return self._analyse_with_strict_prompt(query, conversation_summary)

        except Exception as e:
            print(f"Error in query router: {e}")
            # Return default analysis with basic regex extraction
            return self._default_analysis(query)

    def _analyse_with_strict_prompt(self, query: str, conversation_summary: str) -> QueryAnalysis:
        """Retry with stricter prompt if JSON parsing failed."""
        strict_prompt = f"""You MUST output ONLY a valid JSON object with these exact fields:
- intent: one of "definition", "exception", "procedure", "penalty", "amendment", "general"
- legal_entities: array of strings (e.g. ["Section 17", "CGST Act"])
- graph_seed_labels: array of strings (same as legal_entities)
- expanded_queries: array of 2-3 strings (rephrased versions of the query)
- requires_multi_hop: boolean
- hop_depth: integer (2 or 3)

Do not include any other text, explanation, or formatting.

Query: {query}
Conversation: {conversation_summary}
JSON:"""

        try:
            response = self.llm.create_chat_completion(
                messages=[{"role": "user", "content": strict_prompt}],
                max_tokens=512,
                temperature=0.1  # Lower temperature for more deterministic output
            )

            raw = response["choices"][0]["message"]["content"].strip()
            cleaned = strip_thinking(raw)

            data = json.loads(cleaned)
            return QueryAnalysis(
                original_query=query,
                intent=data.get("intent", "general"),
                legal_entities=data.get("legal_entities", []),
                graph_seed_labels=data.get("graph_seed_labels", []),
                expanded_queries=data.get("expanded_queries", []),
                requires_multi_hop=bool(data.get("requires_multi_hop", False)),
                hop_depth=int(data.get("hop_depth", 2))
            )
        except Exception:
            # If still fails, return default analysis
            return self._default_analysis(query)

    def _default_analysis(self, query: str) -> QueryAnalysis:
        """Fallback analysis using basic regex extraction."""
        # Simple regex to find section numbers and act names
        section_pattern = r'Section\s+\d+[\(\w\d\)\s]*'
        act_pattern = r'(CGST|IGST|SGST|UTGST)\s*Act|\s*(Income\s*Tax|GST|FEMA|ICAI)\s*(Act|Regulations?|Circulars?)'

        legal_entities = []

        # Find section references
        sections = re.findall(section_pattern, query, re.IGNORECASE)
        legal_entities.extend(sections)

        # Find act references
        acts = re.findall(act_pattern, query, re.IGNORECASE)
        # Flatten the tuples from regex groups
        for match in acts:
            for group in match:
                if group:
                    legal_entities.append(group.strip())

        # Clean up duplicates
        legal_entities = list(dict.fromkeys([e.strip() for e in legal_entities if e.strip()]))

        # Format for graph seeds (same as legal entities for now)
        graph_seed_labels = legal_entities.copy()

        # Simple expanded queries
        expanded_queries = [
            query,
            f"What is {query}?" if not query.startswith("What") else query,
            f"How does {query} work?" if "what" in query.lower() else f"Explain {query}"
        ][:3]  # Limit to 3

        # Determine intent based on keywords
        query_lower = query.lower()
        if any(word in query_lower for word in ["what is", "define", "definition", "means"]):
            intent = "definition"
        elif any(word in query_lower for word in ["exception", "exclusion", "proviso", "not applicable"]):
            intent = "exception"
        elif any(word in query_lower for word in ["how to", "procedure", "process", "steps", "file"]):
            intent = "procedure"
        elif any(word in query_lower for word in ["penalty", "fine", "prosecution", "punishment"]):
            intent = "penalty"
        elif any(word in query_lower for word in ["amendment", "change", "revised", "updated"]):
            intent = "amendment"
        else:
            intent = "general"

        return QueryAnalysis(
            original_query=query,
            intent=intent,
            legal_entities=legal_entities,
            graph_seed_labels=graph_seed_labels,
            expanded_queries=expanded_queries,
            requires_multi_hop=len(legal_entities) > 1,  # Simple heuristic
            hop_depth=2 if len(legal_entities) <= 1 else 3
        )