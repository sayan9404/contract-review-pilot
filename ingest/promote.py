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
from ingest.index import (
    ensure_index,
    list_active_documents,
    list_all_documents,
    push_chunks,
    supersede_document,
)
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
        # "New document" -- but the id may already have history if it was
        # promoted before (e.g. promoted, disabled, then promoted again). If
        # so, treat this as a fresh version rather than reusing version 1:
        # reusing it would write new active chunks alongside the old ones
        # under the same version, and any old chunk whose id doesn't collide
        # (different chunking) would linger as a mixed-status orphan. Bump
        # past the highest version ever used and supersede whatever is active.
        history = [d for d in list_all_documents() if d["document_id"] == target_document_id]
        if history:
            version = max(d["version"] for d in history) + 1
            supersede_document(target_document_id)
        else:
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
