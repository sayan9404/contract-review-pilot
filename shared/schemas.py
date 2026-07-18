"""Shared data contracts for the contract-review pipeline.

Field names and shapes mirror the JSON schema fixed in the Technical
Foundation doc, section 8 ("Generation Layer - Grounded Reasoning &
Structured Output"), so ingestion, analysis, report, and eval code all
agree on one shape without re-deriving it.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    doc: Optional[str] = None
    section: Optional[str] = None
    page: Optional[int] = None


class Finding(BaseModel):
    finding_id: str
    category: str
    risk_level: Literal["Low", "Medium", "High", "Legal item"]
    contract_reference: SourceReference
    baseline_reference: Optional[SourceReference] = None
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str
    reviewer_decision: Optional[Literal["accept", "reject", "escalate"]] = None
    no_baseline_found: bool = False
    rules_force_flagged: bool = False
    # Set to False by report.py whenever a finding lacks a valid citation --
    # the "no citation, no accepted finding" rule from Technical Foundation §12.
    citation_verified: bool = True


class CoverageRow(BaseModel):
    contract_area: str
    in_new_contract: bool
    in_baseline: Literal["Yes", "No", "Partial", "n/a"]
    gap: bool
    review: str


class ClauseInventoryEntry(BaseModel):
    clause_id: str
    section: Optional[str] = None
    page: Optional[int] = None
    text: str
    category: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class ClauseInventorySummary(BaseModel):
    source_doc: str
    total_pages: int
    detected_clauses: int
    annexures: int = 0
    tables: int = 0
    low_confidence_sections: list[str] = Field(default_factory=list)


class BaselineChunk(BaseModel):
    """One indexed chunk of a baseline document, with the metadata needed
    for structure-aware retrieval and citation assembly.

    document_id/version/status implement the baseline supersession model: a
    revision of an existing baseline document shares its document_id, bumps
    version, and flips the prior version's chunks to status="superseded"
    (kept for audit, excluded from retrieval by a status=="active" filter)
    rather than deleting them. A genuinely new/unrelated document gets its
    own document_id and coexists with whatever else is active.
    """

    chunk_id: str
    document_id: str = ""  # filled in by ingest/promote.py after chunking
    version: int = 1
    status: Literal["active", "superseded"] = "active"
    source_doc: str
    section: Optional[str] = None
    page: Optional[int] = None
    heading: Optional[str] = None
    text: str
    embedding: Optional[list[float]] = None


class GapReport(BaseModel):
    contract_name: str
    findings: list[Finding]
    coverage_matrix: list[CoverageRow]
    clause_inventory_summary: ClauseInventorySummary
