"""Phase P4: the 4 measurable MVP exit-gate metrics from the proposal's
Recommendation section (Proposal v1.2, section 09) -- clause extraction
quality, citation accuracy, critical miss rate, false positive rate -- plus
retrieval Recall@K from the engineering implementation plan. First-pass
review time and reviewer satisfaction are also in the proposal's table but
are human-process metrics with nothing to compute here.

Matching a labelled_test_set.json clause_ref (e.g. "Section 5.2") against a
parsed/produced section string is done by substring containment, since the
label is a short prefix of the full heading text (e.g. "Section 5.2 --
Support Obligations"). This is intentionally simple and would need to get
more careful (fuzzy/normalized matching) if the labelled test set ever grew
past a handful of clauses per contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from analysis.retrieve import retrieve
from shared.schemas import ClauseInventoryEntry, GapReport

BASELINE_DOC_NAMES = ["SOW_v1.md", "SLA_matrix.md", "policy_security.md", "skills_matrix.csv"]


def _clause_matches(clause_ref: str, section: Optional[str]) -> bool:
    return bool(section) and clause_ref.lower() in section.lower()


def _expected_baseline_docs(expected_match: str) -> list[str]:
    return [doc for doc in BASELINE_DOC_NAMES if doc in expected_match]


@dataclass
class ContractScore:
    contract_name: str
    expected_clauses: int
    extracted_clauses_matched: int
    findings_total: int
    findings_citation_verified: int
    expected_gaps: int
    expected_gaps_missed: list[str] = field(default_factory=list)
    findings_unexpected: list[str] = field(default_factory=list)
    recall_hits: int = 0
    recall_applicable: int = 0

    @property
    def clause_extraction_quality(self) -> Optional[float]:
        if self.expected_clauses == 0:
            return None
        return 100 * self.extracted_clauses_matched / self.expected_clauses

    @property
    def citation_accuracy(self) -> Optional[float]:
        if self.findings_total == 0:
            return None
        return 100 * self.findings_citation_verified / self.findings_total

    @property
    def critical_miss_rate(self) -> Optional[float]:
        if self.expected_gaps == 0:
            return None
        return 100 * len(self.expected_gaps_missed) / self.expected_gaps

    @property
    def false_positive_rate(self) -> Optional[float]:
        if self.findings_total == 0:
            return None
        return 100 * len(self.findings_unexpected) / self.findings_total

    @property
    def recall_at_k(self) -> Optional[float]:
        if self.recall_applicable == 0:
            return None
        return 100 * self.recall_hits / self.recall_applicable


def score_contract(
    contract_name: str,
    clauses: list[ClauseInventoryEntry],
    report: GapReport,
    labelled: dict,
    top_k: int = 3,
) -> ContractScore:
    expected_findings = labelled["expected_findings"]
    expected_gap_refs = [f["clause_ref"] for f in expected_findings if f["gap"]]
    findings = report.findings

    extracted_matched = sum(
        1 for f in expected_findings if any(_clause_matches(f["clause_ref"], c.section) for c in clauses)
    )

    citation_verified = sum(1 for finding in findings if finding.citation_verified)

    missed = [
        ref
        for ref in expected_gap_refs
        if not any(_clause_matches(ref, finding.contract_reference.section) for finding in findings)
    ]

    unexpected = [
        finding.finding_id
        for finding in findings
        if not any(_clause_matches(ref, finding.contract_reference.section) for ref in expected_gap_refs)
    ]

    recall_hits = 0
    recall_applicable = 0
    for f in expected_findings:
        if not f["gap"]:
            continue
        expected_docs = _expected_baseline_docs(f.get("expected_baseline_match", ""))
        if not expected_docs:
            continue  # "no baseline coverage found" -- nothing to recall against
        clause = next((c for c in clauses if _clause_matches(f["clause_ref"], c.section)), None)
        if clause is None:
            continue
        recall_applicable += 1
        retrieved_docs = {p.source_doc for p in retrieve(clause.text, top_k=top_k)}
        if retrieved_docs & set(expected_docs):
            recall_hits += 1

    return ContractScore(
        contract_name=contract_name,
        expected_clauses=len(expected_findings),
        extracted_clauses_matched=extracted_matched,
        findings_total=len(findings),
        findings_citation_verified=citation_verified,
        expected_gaps=len(expected_gap_refs),
        expected_gaps_missed=missed,
        findings_unexpected=unexpected,
        recall_hits=recall_hits,
        recall_applicable=recall_applicable,
    )


@dataclass
class Scorecard:
    contract_scores: list[ContractScore]

    def _pooled(self, numerator: str, denominator: str) -> Optional[float]:
        total = sum(getattr(s, denominator) for s in self.contract_scores)
        if total == 0:
            return None
        matched = sum(
            len(getattr(s, numerator)) if isinstance(getattr(s, numerator), list) else getattr(s, numerator)
            for s in self.contract_scores
        )
        return 100 * matched / total

    @property
    def clause_extraction_quality(self) -> Optional[float]:
        return self._pooled("extracted_clauses_matched", "expected_clauses")

    @property
    def citation_accuracy(self) -> Optional[float]:
        return self._pooled("findings_citation_verified", "findings_total")

    @property
    def critical_miss_rate(self) -> Optional[float]:
        return self._pooled("expected_gaps_missed", "expected_gaps")

    @property
    def false_positive_rate(self) -> Optional[float]:
        return self._pooled("findings_unexpected", "findings_total")

    @property
    def recall_at_k(self) -> Optional[float]:
        return self._pooled("recall_hits", "recall_applicable")
