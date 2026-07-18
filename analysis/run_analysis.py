"""Phase P3 orchestrator: parse one new contract -> rules scan -> retrieve ->
generate -> report, end to end.

Usage: python analysis/run_analysis.py <path-to-contract.md|.pdf|.docx>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.generate import ClauseAssessment, assess_clause  # noqa: E402
from analysis.parse_contract import extract_clauses, summarize_contract  # noqa: E402
from analysis.report import build_report  # noqa: E402
from analysis.retrieve import retrieve  # noqa: E402
from analysis.rules import scan_clauses  # noqa: E402
from ingest.parse import parse_document_file  # noqa: E402
from shared.schemas import GapReport  # noqa: E402


def run_analysis(contract_path: Path) -> GapReport:
    doc = parse_document_file(contract_path)
    clauses = extract_clauses(doc)
    rule_matches = scan_clauses(clauses)

    assessments: list[ClauseAssessment] = []
    for clause in clauses:
        passages = retrieve(clause.text)
        assessments.append(assess_clause(clause, passages))

    clause_summary = summarize_contract(doc, clauses)
    return build_report(contract_path.stem, assessments, rule_matches, clause_summary)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analysis/run_analysis.py <path-to-contract.md>")
        sys.exit(1)
    report = run_analysis(Path(sys.argv[1]))
    print(json.dumps(report.model_dump(), indent=2))
