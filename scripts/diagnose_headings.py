"""One-off diagnostic: dump every element Document Intelligence returns for
a PDF, with its role and text, so we can see exactly what got tagged as a
heading vs. not -- used to debug why extract_clauses() undercounts clauses
on real multi-section contracts. Not part of the pipeline; delete once the
root cause is confirmed.

Usage: python scripts/diagnose_headings.py <path-to.pdf>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import azure_clients as az  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_headings.py <path-to.pdf>")
        sys.exit(1)

    path = Path(sys.argv[1])
    client = az.get_document_intelligence_client()
    poller = client.begin_analyze_document(
        "prebuilt-layout", body=path.read_bytes(), content_type="application/pdf"
    )
    result = poller.result()

    print(f"total pages (DI): {len(result.pages)}")
    print(f"total paragraphs: {len(result.paragraphs or [])}")
    print(f"total tables: {len(result.tables or [])}")
    print()

    print("=== paragraphs, in document order, with role ===")
    for p in result.paragraphs or []:
        page = p.bounding_regions[0].page_number if p.bounding_regions else "?"
        role = str(p.role) if p.role else "(none)"
        print(f"[page {page}] role={role!r}  text={p.content[:80]!r}")

    print()
    print("=== tables ===")
    for i, t in enumerate(result.tables or [], start=1):
        page = t.bounding_regions[0].page_number if t.bounding_regions else "?"
        print(f"table {i}: page={page} rows={t.row_count} cols={t.column_count}")


if __name__ == "__main__":
    main()
