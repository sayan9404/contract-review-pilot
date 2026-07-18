"""Phase P4 orchestrator: run analysis/run_analysis.py over every contract in
data/labelled_test_set.json, score each against the label using
eval/metrics.py, and print a scorecard against the MVP exit-gate targets
from the proposal (Proposal v1.2, section 09) plus retrieval Recall@K from
the engineering implementation plan.

Usage: python eval/run_eval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.parse_contract import extract_clauses  # noqa: E402
from analysis.run_analysis import run_analysis  # noqa: E402
from eval.metrics import ContractScore, Scorecard, score_contract  # noqa: E402
from ingest.parse import parse_document_file  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LABELLED_SET_PATH = _REPO_ROOT / "data" / "labelled_test_set.json"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}%"


def _print_per_contract(scores: list[ContractScore]) -> None:
    print("=== Per-contract ===")
    for s in scores:
        print(f"\n{s.contract_name}")
        print(
            f"  Clause extraction quality : {_fmt(s.clause_extraction_quality)} "
            f"({s.extracted_clauses_matched}/{s.expected_clauses})"
        )
        print(
            f"  Citation accuracy         : {_fmt(s.citation_accuracy)} "
            f"({s.findings_citation_verified}/{s.findings_total})"
        )
        miss_note = f"  MISSED: {s.expected_gaps_missed}" if s.expected_gaps_missed else ""
        print(f"  Critical miss rate        : {_fmt(s.critical_miss_rate)}{miss_note}")
        fp_note = f"  UNEXPECTED: {s.findings_unexpected}" if s.findings_unexpected else ""
        print(f"  False positive rate       : {_fmt(s.false_positive_rate)}{fp_note}")
        print(f"  Retrieval Recall@K        : {_fmt(s.recall_at_k)} ({s.recall_hits}/{s.recall_applicable})")


def _print_scorecard(scorecard: Scorecard) -> None:
    print("\n=== Scorecard vs. MVP exit-gate targets (Proposal v1.2, section 09) ===")
    rows = [
        ("Clause extraction quality", scorecard.clause_extraction_quality, "90%+", lambda v: v >= 90),
        ("Citation accuracy", scorecard.citation_accuracy, "90%+ w/ correct source ref", lambda v: v >= 90),
        ("Critical miss rate", scorecard.critical_miss_rate, "Zero", lambda v: v == 0),
        ("False positive rate", scorecard.false_positive_rate, "Below ~25-30%", lambda v: v <= 30),
    ]
    for name, value, target, passes in rows:
        status = "N/A" if value is None else ("PASS" if passes(value) else "FAIL")
        print(f"  {name:<28} {_fmt(value):>6}  (target: {target:<28}) [{status}]")

    print(
        f"  {'Retrieval Recall@K':<28} {_fmt(scorecard.recall_at_k):>6}  "
        "(informational -- not in the proposal's MVP table)"
    )

    print("\nNot computed here (human-process metrics from the proposal, not automatable):")
    print("  - First-pass review time (target: 1-2 days to a few hours)")
    print("  - Reviewer satisfaction (target: 4/5+)")


def main() -> None:
    labelled = json.loads(_LABELLED_SET_PATH.read_text(encoding="utf-8"))
    scores: list[ContractScore] = []

    for key, entry in labelled.items():
        contract_path = _REPO_ROOT / entry["file"]
        print(f"Running analysis: {contract_path.name} ...", file=sys.stderr)
        report = run_analysis(contract_path)
        doc = parse_document_file(contract_path)
        clauses = extract_clauses(doc)
        scores.append(score_contract(key, clauses, report, entry))

    scorecard = Scorecard(scores)
    _print_per_contract(scores)
    _print_scorecard(scorecard)


if __name__ == "__main__":
    main()
