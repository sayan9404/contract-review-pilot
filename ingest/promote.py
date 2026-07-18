"""Promote a parsed document into the baseline knowledge base.

Two paths, chosen explicitly by whoever calls this (a human, via the UI --
never inferred automatically):

- New document: gets a fresh document_id, version=1, status="active".
- Revision of an existing document: shares that document_id, gets
  version = prior_version + 1, status="active"; the prior version's chunks
  are flipped to status="superseded" via ingest.index.supersede_document --
  kept for audit, just excluded from retrieval (analysis/retrieve.py filters
  on status=="active"), never deleted.
"""
from __future__ import annotations

import re
from typing import Optional

from ingest.chunk import chunk_document
from ingest.embed import embed_chunks
from ingest.index import ensure_index, list_active_documents, push_chunks, supersede_document
from ingest.parse import ParsedDocument
from shared.schemas import BaselineChunk


def slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "-", name).strip("-").lower()


def promote_to_baseline(
    doc: ParsedDocument,
    *,
    document_id: Optional[str] = None,
    supersedes: Optional[str] = None,
) -> list[BaselineChunk]:
    if bool(document_id) == bool(supersedes):
        raise ValueError(
            "Provide exactly one of document_id (new document) or "
            "supersedes (revision of an existing document_id)."
        )

    ensure_index()

    if supersedes:
        existing = {d["document_id"]: d for d in list_active_documents()}
        prior = existing.get(supersedes)
        if prior is None:
            raise ValueError(f"No active baseline document found for document_id={supersedes!r}")
        target_document_id = supersedes
        version = prior["version"] + 1
        supersede_document(supersedes)
    else:
        target_document_id = document_id
        version = 1

    chunks = chunk_document(doc)
    for chunk in chunks:
        chunk.chunk_id = f"{target_document_id}-v{version}-{chunk.chunk_id}"
        chunk.document_id = target_document_id
        chunk.version = version
        chunk.status = "active"

    embed_chunks(chunks)
    push_chunks(chunks)
    return chunks
