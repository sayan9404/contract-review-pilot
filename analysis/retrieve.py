"""Phase P3 step 3: hybrid (keyword + vector) retrieval against the P2
baseline index, with semantic reranking applied opportunistically. The plan
assumed semantic ranking would need a temporary Basic-tier upgrade (see
HANDOFF.md), but it works live on this Free-tier service -- this still
falls back to plain hybrid search on any error, in case that changes or the
service tier does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from azure.core.exceptions import HttpResponseError
from azure.search.documents.models import VectorizedQuery

from ingest.index import INDEX_NAME, SEMANTIC_CONFIG_NAME
from shared import azure_clients as az

TOP_K = 3
_ACTIVE_ONLY_FILTER = "status eq 'active'"
_warned_no_semantic = False


@dataclass
class RetrievedPassage:
    text: str
    source_doc: str
    section: Optional[str]
    page: Optional[int]
    score: float


def _to_passages(results) -> list[RetrievedPassage]:
    return [
        RetrievedPassage(
            text=r["text"],
            source_doc=r["source_doc"],
            section=r.get("section"),
            page=r.get("page"),
            score=r.get("@search.score", 0.0),
        )
        for r in results
    ]


def retrieve(clause_text: str, top_k: int = TOP_K) -> list[RetrievedPassage]:
    global _warned_no_semantic
    search_client = az.get_search_client(INDEX_NAME)
    openai_client = az.get_openai_client()

    embedding = openai_client.embeddings.create(
        model=az.EMBEDDING_DEPLOYMENT, input=clause_text
    ).data[0].embedding
    vector_query = VectorizedQuery(vector=embedding, k_nearest_neighbors=top_k, fields="embedding")

    try:
        results = search_client.search(
            search_text=clause_text,
            vector_queries=[vector_query],
            query_type="semantic",
            semantic_configuration_name=SEMANTIC_CONFIG_NAME,
            filter=_ACTIVE_ONLY_FILTER,
            top=top_k,
        )
        return _to_passages(results)
    except HttpResponseError as exc:
        if not _warned_no_semantic:
            print(f"[retrieve] semantic ranking unavailable ({exc}); falling back to hybrid search")
            _warned_no_semantic = True
        results = search_client.search(
            search_text=clause_text, vector_queries=[vector_query], filter=_ACTIVE_ONLY_FILTER, top=top_k
        )
        return _to_passages(results)
