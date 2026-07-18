"""Phase P2 step 4: create the Azure AI Search index and push embedded
baseline chunks into it.

Semantic search config is declared here. The plan assumed it'd need a
temporary Basic-tier upgrade to be queryable (see HANDOFF.md P1 notes), but
it turned out to work live on this Free-tier service -- analysis/retrieve.py
still falls back to plain hybrid search defensively in case that changes.
"""
from __future__ import annotations

from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

from shared import azure_clients as az
from shared.schemas import BaselineChunk

INDEX_NAME = "contractreview-baseline"
EMBEDDING_DIMENSIONS = 3072  # text-embedding-3-large output size
_VECTOR_ALGORITHM = "hnsw-default"
_VECTOR_PROFILE = "vector-profile-default"
SEMANTIC_CONFIG_NAME = "semantic-default"


def build_index_definition() -> SearchIndex:
    fields = [
        SimpleField(name="chunk_id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="text", type=SearchFieldDataType.String),
        SimpleField(name="source_doc", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="document_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="version", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="status", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="section", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="heading", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="page", type=SearchFieldDataType.Int32, filterable=True),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name=_VECTOR_PROFILE,
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name=_VECTOR_ALGORITHM)],
        profiles=[
            VectorSearchProfile(
                name=_VECTOR_PROFILE,
                algorithm_configuration_name=_VECTOR_ALGORITHM,
            )
        ],
    )

    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="heading"),
                    content_fields=[SemanticField(field_name="text")],
                ),
            )
        ]
    )

    return SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )


def ensure_index() -> None:
    client = az.get_search_index_client()
    client.create_or_update_index(build_index_definition())


def push_chunks(chunks: list[BaselineChunk]) -> None:
    if not chunks:
        return
    client = az.get_search_client(INDEX_NAME)
    documents = [
        {
            "chunk_id": chunk.chunk_id,
            "text": chunk.text,
            "source_doc": chunk.source_doc,
            "document_id": chunk.document_id,
            "version": chunk.version,
            "status": chunk.status,
            "section": chunk.section,
            "heading": chunk.heading,
            "page": chunk.page,
            "embedding": chunk.embedding,
        }
        for chunk in chunks
    ]
    client.merge_or_upload_documents(documents=documents)


def _update_status(filter_expr: str, status: str) -> int:
    """Metadata-only partial update: set status on every chunk matching
    filter_expr. text/embedding/etc. untouched, nothing ever deleted."""
    client = az.get_search_client(INDEX_NAME)
    results = list(client.search(search_text="*", filter=filter_expr, select=["chunk_id"], top=1000))
    if not results:
        return 0
    client.merge_or_upload_documents(documents=[{"chunk_id": r["chunk_id"], "status": status} for r in results])
    return len(results)


def supersede_document(document_id: str) -> int:
    """Flip every active chunk of document_id to status="superseded".
    Returns how many chunks were retired. Used both when promoting a
    revision and for a manual "disable" action -- the old version stays in
    the index for audit but is excluded from retrieval by
    analysis/retrieve.py's status=="active" filter.
    """
    return _update_status(f"document_id eq '{document_id}' and status eq 'active'", "superseded")


def activate_version(document_id: str, version: int) -> int:
    """Make (document_id, version) the active one -- supersedes whatever
    else is currently active for document_id first (a no-op if nothing is),
    preserving the single-active-version-per-document invariant, then
    activates the requested version. Powers the UI's "enable"/rollback
    action for a previously-disabled version.
    """
    supersede_document(document_id)
    return _update_status(f"document_id eq '{document_id}' and version eq {version}", "active")


def list_all_documents() -> list[dict]:
    """Every (document_id, version) ever pushed, active or superseded --
    the full history, for the UI's "show disabled versions too" view."""
    client = az.get_search_client(INDEX_NAME)
    results = client.search(
        search_text="*", select=["document_id", "version", "source_doc", "status"], top=1000
    )
    seen: dict[tuple, dict] = {}
    for r in results:
        if not r["document_id"]:
            continue  # pre-versioning orphan rows from before this feature existed
        key = (r["document_id"], r["version"])
        seen.setdefault(
            key,
            {"document_id": r["document_id"], "version": r["version"], "source_doc": r["source_doc"], "status": r["status"]},
        )
    return sorted(seen.values(), key=lambda d: (d["document_id"], d["version"]))


def list_active_documents() -> list[dict]:
    """One row per distinct active document_id, for the baseline-promotion
    UI's "does this supersede an existing document?" picker."""
    return [d for d in list_all_documents() if d["status"] == "active"]
