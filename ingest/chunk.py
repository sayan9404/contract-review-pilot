"""Phase P2 step 2: structure-aware chunking of parsed baseline documents,
per config/chunking.json.

Splits on section/heading boundaries first (each section becomes its own
run of chunks, never merged with a neighboring section), then applies a
token-window with overlap inside a section only if that section is longer
than max_tokens. Tables are always kept intact as their own chunk.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import tiktoken

from ingest.parse import ParsedDocument, ParsedElement
from shared.schemas import BaselineChunk

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "chunking.json"
_ENCODING = tiktoken.get_encoding("cl100k_base")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _load_config() -> dict:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _overlap_carry(buffer: list[str], max_tokens: int, overlap_pct: float) -> list[str]:
    """Trailing sentences from a just-closed chunk to seed the next one with,
    worth roughly overlap_pct% of max_tokens."""
    if not buffer or overlap_pct <= 0:
        return []
    target = max_tokens * overlap_pct / 100
    carried: list[str] = []
    running = 0
    for sentence in reversed(buffer):
        tokens = _count_tokens(sentence)
        if carried and running + tokens > target:
            break
        carried.insert(0, sentence)
        running += tokens
    return carried


def _group_by_section(elements: list[ParsedElement]) -> list[list[ParsedElement]]:
    sections: list[list[ParsedElement]] = []
    for element in elements:
        if element.kind == "heading" or not sections:
            sections.append([])
        sections[-1].append(element)
    return sections


def chunk_document(doc: ParsedDocument, config: Optional[dict] = None) -> list[BaselineChunk]:
    cfg = config or _load_config()
    max_tokens = cfg["max_tokens"]
    overlap_pct = cfg["overlap_pct"]
    respect_sentences = cfg.get("respect_sentence_boundaries", True)
    keep_tables_intact = cfg.get("keep_tables_intact", True)

    chunks: list[BaselineChunk] = []
    counter = 0

    doc_key = re.sub(r"[^A-Za-z0-9_\-=]", "-", doc.source_doc)

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"{doc_key}-chunk-{counter}"

    for section_elements in _group_by_section(doc.elements):
        section_name = next((e.section for e in section_elements if e.section), None)
        page = next((e.page for e in section_elements if e.page is not None), None)

        def flush(text_parts: list[str]) -> None:
            if not text_parts:
                return
            chunks.append(
                BaselineChunk(
                    chunk_id=next_id(),
                    source_doc=doc.source_doc,
                    section=section_name,
                    page=page,
                    heading=section_name,
                    text=" ".join(text_parts).strip(),
                )
            )

        # Text shorter than one overlap-carry window is, by the system's own
        # definition, context rather than a standalone chunk (it's the exact
        # amount we bleed between adjacent windows). A pre-table buffer below
        # this is folded into the table's chunk even when the two don't fit
        # the budget together -- never left as a near-empty chunk beside the
        # table. Above it, the buffer is real prose that earns its own chunk.
        min_standalone_tokens = max_tokens * overlap_pct / 100

        buffer: list[str] = []
        for element in section_elements:
            if element.kind == "table" and keep_tables_intact:
                # Fold any preceding buffer (typically just the heading,
                # sometimes plus a fragment DI split off this same table --
                # e.g. a header row left on the prior page when a table
                # crosses a page break) into the table's own chunk whenever
                # it fits the budget, OR whenever the buffer is too small to
                # stand alone. Otherwise a small leftover sits right next to
                # its table's real content as a near-duplicate that can
                # outrank it in retrieval on nothing but query-embedding
                # jitter between runs -- the exact failure mode behind the
                # "same clause, different verdict across runs" bug. Only a
                # buffer that is both substantial AND over budget is split
                # off on its own; that is real prose, never a degenerate
                # near-empty competitor. Tables are kept intact and already
                # run over the target size, so folding a small buffer in adds
                # negligible bulk.
                buffer_tokens = _count_tokens(" ".join(buffer)) if buffer else 0
                combined_fits = _count_tokens(" ".join([*buffer, element.text])) <= max_tokens
                if buffer and (combined_fits or buffer_tokens < min_standalone_tokens):
                    flush([*buffer, element.text])
                else:
                    flush(buffer)
                    flush([element.text])
                buffer = []
                continue

            sentences = _split_sentences(element.text) if respect_sentences else [element.text]
            for sentence in sentences:
                candidate = buffer + [sentence]
                if buffer and _count_tokens(" ".join(candidate)) > max_tokens:
                    flush(buffer)
                    buffer = _overlap_carry(buffer, max_tokens, overlap_pct)
                buffer.append(sentence)

        flush(buffer)

    return chunks
