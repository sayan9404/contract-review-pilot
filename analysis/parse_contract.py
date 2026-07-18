"""Phase P3 step 1: parse one new contract into a clause inventory. Reuses
ingest/parse.py's Document Intelligence pipeline (same Layout-model approach
as the baseline docs), then groups elements into one clause per heading-
delimited section -- matching how the labelled test set references clauses
(e.g. "Section 5.2"), unlike ingest/chunk.py's token-window chunking which
is tuned for baseline retrieval, not clause-by-clause review.
"""
from __future__ import annotations

from typing import Optional

from ingest.parse import ParsedDocument
from shared.schemas import ClauseInventoryEntry, ClauseInventorySummary

# Every synthetic doc in this repo opens with this marker (see data/ and
# HANDOFF.md's data policy) -- filtered out so the disclaimer line never
# turns into a fake "clause" fed to the rules/retrieval/generation layers.
_DISCLAIMER_PREFIX = "[SYNTHETIC"

_LOW_CONFIDENCE_THRESHOLD = 0.85


def extract_clauses(doc: ParsedDocument) -> list[ClauseInventoryEntry]:
    clauses: list[ClauseInventoryEntry] = []
    current_heading: Optional[str] = None
    buffer: list[str] = []
    counter = 0

    def flush() -> None:
        nonlocal counter
        text = " ".join(buffer).strip()
        if not text or text.startswith(_DISCLAIMER_PREFIX):
            return
        counter += 1
        clauses.append(
            ClauseInventoryEntry(
                clause_id=f"{doc.source_doc}-clause-{counter}",
                section=current_heading,
                text=text,
            )
        )

    for element in doc.elements:
        if element.kind == "heading":
            flush()
            buffer = []
            current_heading = element.text
            continue
        buffer.append(element.text)

    flush()
    return clauses


def summarize_contract(doc: ParsedDocument, clauses: list[ClauseInventoryEntry]) -> ClauseInventorySummary:
    tables = sum(1 for e in doc.elements if e.kind == "table")
    if doc.avg_confidence < _LOW_CONFIDENCE_THRESHOLD:
        low_confidence = sorted({c.section for c in clauses if c.section})
    else:
        low_confidence = []
    return ClauseInventorySummary(
        source_doc=doc.source_doc,
        total_pages=doc.total_pages,
        detected_clauses=len(clauses),
        tables=tables,
        low_confidence_sections=low_confidence,
    )
