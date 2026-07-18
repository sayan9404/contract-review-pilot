"""Phase P2 orchestrator: parse -> chunk -> embed -> index over every file in
data/synthetic_baseline/, then print a clause-inventory summary per doc --
the architecture doc's M2 validation gate (confirm nothing got silently
dropped by eyeballing page/clause/table counts against the real doc content).

Each file is promoted as a fresh document_id (version=1, status=active) via
ingest/promote.py -- this is what establishes the initial baseline state
that later revisions (through the UI's "add to baseline" flow) supersede.
Re-running this is idempotent: same document_id + deterministic chunk_ids
means it just overwrites the same v1 chunks in place.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.parse import ParsedDocument, parse_document_file  # noqa: E402
from ingest.promote import promote_to_baseline, slugify  # noqa: E402
from shared.schemas import ClauseInventorySummary  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic_baseline"
_LOW_CONFIDENCE_THRESHOLD = 0.85


def summarize(doc: ParsedDocument) -> ClauseInventorySummary:
    tables = sum(1 for e in doc.elements if e.kind == "table")
    clauses = sum(1 for e in doc.elements if e.kind in ("paragraph", "table"))
    if doc.avg_confidence < _LOW_CONFIDENCE_THRESHOLD:
        sections = sorted({e.section for e in doc.elements if e.section} or {doc.source_doc})
    else:
        sections = []
    return ClauseInventorySummary(
        source_doc=doc.source_doc,
        total_pages=doc.total_pages,
        detected_clauses=clauses,
        tables=tables,
        low_confidence_sections=sections,
    )


def run() -> list[ClauseInventorySummary]:
    summaries: list[ClauseInventorySummary] = []

    for path in sorted(BASELINE_DIR.iterdir()):
        if path.suffix.lower() not in (".md", ".csv"):
            continue
        doc = parse_document_file(path)
        promote_to_baseline(doc, document_id=slugify(path.stem))
        summaries.append(summarize(doc))

    return summaries


def print_report(summaries: list[ClauseInventorySummary]) -> None:
    print(f"{'doc':35} {'pages':>5} {'clauses':>8} {'tables':>7}  low-confidence sections")
    for s in summaries:
        flag = ", ".join(s.low_confidence_sections) or "-"
        print(f"{s.source_doc:35} {s.total_pages:>5} {s.detected_clauses:>8} {s.tables:>7}  {flag}")


if __name__ == "__main__":
    print_report(run())
