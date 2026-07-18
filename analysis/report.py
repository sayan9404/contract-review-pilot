"""Phase P3 step 5: assemble findings + coverage matrix + citations into one
GapReport.

Enforces the "no citation, no accepted finding" rule from Technical
Foundation section 12: a finding is only marked citation_verified=True if
it's backed by something concrete -- a deterministic rules-layer
force-flag, an explicit "checked the baseline, found nothing" result, or a
real (index-resolved, not model-invented) baseline citation. Anything else
is marked unverified rather than shown as accepted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from analysis.generate import ClauseAssessment
from analysis.rules import RuleMatch
from shared.schemas import (
    ClauseInventorySummary,
    CoverageRow,
    Finding,
    GapReport,
    SourceReference,
)

_CATEGORIES_PATH = Path(__file__).resolve().parent.parent / "config" / "categories.json"
_CATEGORIES: list[str] = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))


def _citation_verified(
    rules_force_flagged: bool, no_baseline_found: bool, baseline_reference: Optional[SourceReference]
) -> bool:
    if rules_force_flagged or no_baseline_found:
        return True
    return baseline_reference is not None and bool(baseline_reference.doc)


def build_findings(
    assessments: list[ClauseAssessment], rule_matches: dict[str, RuleMatch]
) -> list[Finding]:
    findings: list[Finding] = []
    for assessment in assessments:
        rule_match = rule_matches.get(assessment.clause.clause_id)
        force_flagged = bool(rule_match and rule_match.force_flagged)

        # A clause only becomes a Finding if it's an actual gap, or the
        # deterministic rules layer force-flagged it regardless of the LLM's
        # own judgment -- this is what keeps critical-miss rate at zero even
        # if the model itself judges a critical-term clause as no-gap.
        if not (assessment.gap or force_flagged):
            continue

        risk_level = assessment.risk_level
        if force_flagged and rule_match.legal_override:
            risk_level = "Legal item"

        citation_verified = _citation_verified(
            force_flagged, assessment.no_baseline_found, assessment.baseline_reference
        )

        findings.append(
            Finding(
                finding_id=f"F{len(findings) + 1:03d}",
                category=assessment.category,
                risk_level=risk_level,
                contract_reference=SourceReference(section=assessment.clause.section),
                baseline_reference=assessment.baseline_reference,
                reason=assessment.reason,
                confidence=assessment.confidence,
                recommended_action=assessment.recommended_action,
                no_baseline_found=assessment.no_baseline_found,
                rules_force_flagged=force_flagged,
                citation_verified=citation_verified,
            )
        )
    return findings


def build_coverage_matrix(
    assessments: list[ClauseAssessment], findings: list[Finding]
) -> list[CoverageRow]:
    by_category: dict[str, list[ClauseAssessment]] = {}
    for assessment in assessments:
        by_category.setdefault(assessment.category, []).append(assessment)
    findings_by_category: dict[str, list[Finding]] = {}
    for finding in findings:
        findings_by_category.setdefault(finding.category, []).append(finding)

    rows: list[CoverageRow] = []
    for category in _CATEGORIES:
        clause_assessments = by_category.get(category, [])
        if not clause_assessments:
            rows.append(
                CoverageRow(
                    contract_area=category,
                    in_new_contract=False,
                    in_baseline="n/a",
                    gap=False,
                    review="Not addressed in this contract.",
                )
            )
            continue

        matched = [a for a in clause_assessments if not a.no_baseline_found]
        if not matched:
            in_baseline = "No"
        elif len(matched) == len(clause_assessments):
            in_baseline = "Yes"
        else:
            in_baseline = "Partial"

        # A real gap means the LLM itself judged some clause in this
        # category as gap=True -- NOT merely "a Finding exists here", since
        # build_findings() also creates Findings for clauses the rules layer
        # force-flagged even when the LLM said gap=False (by design, so a
        # critical-term clause always reaches human review regardless of the
        # model's own confidence). Conflating the two used to mark a whole
        # category as gap=True off of a force-flag alone, even when every
        # clause in it was genuinely fine.
        gap = any(a.gap for a in clause_assessments)
        rules_flagged_only = not gap and any(f.rules_force_flagged for f in findings_by_category.get(category, []))
        if gap:
            review = f"{len(clause_assessments)} clause(s); flagged as gap."
        elif rules_flagged_only:
            review = f"{len(clause_assessments)} clause(s); rules-flagged for review, no confirmed gap."
        else:
            review = f"{len(clause_assessments)} clause(s); no gap flagged."
        rows.append(
            CoverageRow(contract_area=category, in_new_contract=True, in_baseline=in_baseline, gap=gap, review=review)
        )
    return rows


def build_report(
    contract_name: str,
    assessments: list[ClauseAssessment],
    rule_matches: dict[str, RuleMatch],
    clause_summary: ClauseInventorySummary,
) -> GapReport:
    findings = build_findings(assessments, rule_matches)
    coverage_matrix = build_coverage_matrix(assessments, findings)
    return GapReport(
        contract_name=contract_name,
        findings=findings,
        coverage_matrix=coverage_matrix,
        clause_inventory_summary=clause_summary,
    )
