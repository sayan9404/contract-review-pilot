"""Parse baseline and contract documents into structured elements using
Document Intelligence's Layout model.

PDF and DOCX are DI's native formats -- sent to the service as-is. Markdown
docs are converted to a minimal HTML document first, since prebuilt-layout
has no native Markdown support but does support HTML; the conversion gives
DI real heading/table structure to detect rather than skipping the service
entirely. CSV files are pure tabular reference data with no clause text, so
they're parsed directly with pandas instead -- DI adds nothing for content
that's already structured.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import markdown
import pandas as pd
import pypdf

from shared import azure_clients as az

ElementKind = Literal["heading", "paragraph", "table"]

# Formats DI's prebuilt-layout model accepts natively -- no conversion step.
_NATIVE_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class TruncatedAnalysisError(RuntimeError):
    """Document Intelligence returned fewer pages than the source PDF
    actually has. Almost always means the resource is on the Free (F0)
    pricing tier, which silently caps analysis at 2 pages per document --
    no error or warning field in the API response indicates this, so it has
    to be caught by comparing against the real page count. Fix: upgrade the
    Document Intelligence resource to S0 in the Azure Portal (Resource
    Management -> Pricing tier). See HANDOFF.md."""


@dataclass
class ParsedElement:
    kind: ElementKind
    text: str
    section: Optional[str]
    page: Optional[int]


@dataclass
class ParsedDocument:
    source_doc: str
    total_pages: int
    elements: list[ParsedElement] = field(default_factory=list)
    avg_confidence: float = 1.0


def _render_table(table) -> str:
    """Render a DI table as a pipe-delimited markdown string so downstream
    chunking can keep the whole thing intact as one block."""
    grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
    for cell in table.cells:
        grid[cell.row_index][cell.column_index] = cell.content.replace("\n", " ").strip()
    lines = ["| " + " | ".join(row) + " |" for row in grid]
    if table.row_count > 1:
        lines.insert(1, "| " + " | ".join(["---"] * table.column_count) + " |")
    return "\n".join(lines)


def _avg_word_confidence(result) -> float:
    confidences = [w.confidence for page in result.pages for w in (page.words or [])]
    return sum(confidences) / len(confidences) if confidences else 1.0


def _page_of(item) -> Optional[int]:
    return item.bounding_regions[0].page_number if item.bounding_regions else None


def _analyze(content: bytes, content_type: str):
    client = az.get_document_intelligence_client()
    poller = client.begin_analyze_document("prebuilt-layout", body=content, content_type=content_type)
    return poller.result()


def _is_table_cell_occurrence(spans, table_cell_spans: list[tuple[int, int]]) -> bool:
    if not spans:
        return False
    start, end = spans[0].offset, spans[0].offset + spans[0].length
    return any(start < cell_end and end > cell_start for cell_start, cell_end in table_cell_spans)


def _to_parsed_document(source_doc: str, result) -> ParsedDocument:
    # DI emits table cell content both inside `tables` and as standalone
    # `paragraphs` -- drop the paragraph duplicates so cells aren't chunked
    # twice, once as loose text and once as part of their table.
    #
    # This has to be a *position* check (does the paragraph's span overlap a
    # cell's own span), not a text-value check. An earlier version compared
    # text values, which wrongly ate every real section heading whose text
    # also happened to appear as a Table of Contents entry -- "1. Purpose"
    # on page 3 is a different physical occurrence than the "1. Purpose"
    # listed in a page-2 TOC table, even though the string is identical.
    table_cell_spans: list[tuple[int, int]] = [
        (span.offset, span.offset + span.length)
        for table in (result.tables or [])
        for cell in table.cells
        for span in (cell.spans or [])
    ]

    # Interleave paragraphs and tables into true reading order using each
    # item's character offset in the source document.
    items: list[tuple[int, str, object]] = []
    for paragraph in result.paragraphs or []:
        if paragraph.spans:
            items.append((paragraph.spans[0].offset, "paragraph", paragraph))
    for table in result.tables or []:
        if table.spans:
            items.append((table.spans[0].offset, "table", table))
    items.sort(key=lambda item: item[0])

    elements: list[ParsedElement] = []
    current_section: Optional[str] = None
    for _, kind, obj in items:
        if kind == "table":
            elements.append(ParsedElement("table", _render_table(obj), current_section, _page_of(obj)))
            continue
        content = obj.content.strip()
        if not content or _is_table_cell_occurrence(obj.spans, table_cell_spans):
            continue
        role = str(obj.role) if obj.role else ""
        role_lower = role.lower()
        # Running headers/footers/page numbers repeat on every page and
        # carry no contract content -- left in, they pollute whatever
        # chunk/clause happens to be accumulating when a page boundary
        # falls mid-section (e.g. a table spanning two pages), sometimes
        # inflating a near-empty fragment enough to look like real content.
        if "page_header" in role_lower or "page_footer" in role_lower or "page_number" in role_lower:
            continue
        page = _page_of(obj)
        if "heading" in role_lower or "title" in role_lower:
            current_section = content
            elements.append(ParsedElement("heading", content, current_section, page))
        else:
            elements.append(ParsedElement("paragraph", content, current_section, page))

    return ParsedDocument(
        source_doc=source_doc,
        total_pages=len(result.pages),
        elements=elements,
        avg_confidence=_avg_word_confidence(result),
    )


def parse_markdown_file(path: Path) -> ParsedDocument:
    md_text = path.read_text(encoding="utf-8")
    body_html = markdown.markdown(md_text, extensions=["tables"])
    html = f"<html><head><meta charset='utf-8'></head><body>{body_html}</body></html>"
    result = _analyze(html.encode("utf-8"), "text/html")
    return _to_parsed_document(path.name, result)


def parse_office_file(path: Path) -> ParsedDocument:
    """PDF or DOCX -- DI's native formats, sent as-is, no conversion."""
    content_type = _NATIVE_CONTENT_TYPES.get(path.suffix.lower())
    if content_type is None:
        raise ValueError(f"Not a supported native format: {path.suffix} ({path.name})")
    content = path.read_bytes()
    result = _analyze(content, content_type)

    if path.suffix.lower() == ".pdf":
        actual_pages = len(pypdf.PdfReader(io.BytesIO(content)).pages)
        if len(result.pages) < actual_pages:
            raise TruncatedAnalysisError(
                f"{path.name}: Document Intelligence only analyzed {len(result.pages)} of "
                f"{actual_pages} pages. This resource is almost certainly on the Free (F0) "
                "pricing tier, which silently caps analysis at 2 pages per document -- the "
                "API gives no error, just fewer pages back. Upgrade to S0 in the Azure Portal "
                "(docintel-contractreview-pilot -> Resource Management -> Pricing tier) and "
                "re-run. See HANDOFF.md for details."
            )

    return _to_parsed_document(path.name, result)


def parse_csv_file(path: Path) -> ParsedDocument:
    df = pd.read_csv(path)
    header = "| " + " | ".join(df.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(df.columns)) + " |"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    table_text = "\n".join([header, sep, *rows])
    element = ParsedElement("table", table_text, None, None)
    return ParsedDocument(source_doc=path.name, total_pages=1, elements=[element])


def parse_document_file(path: Path) -> ParsedDocument:
    """Dispatch by extension -- used for both baseline docs and contracts."""
    suffix = path.suffix.lower()
    if suffix == ".md":
        return parse_markdown_file(path)
    if suffix == ".csv":
        return parse_csv_file(path)
    if suffix in _NATIVE_CONTENT_TYPES:
        return parse_office_file(path)
    raise ValueError(f"Unsupported file type: {suffix} ({path.name})")
