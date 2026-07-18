"""Phase P4 step 3: minimal human-review CLI. Runs one contract through the
full analysis pipeline, lists every finding, and lets a reviewer mark each
accept/reject/escalate -- writing the decision back into
Finding.reviewer_decision and saving the updated report as JSON. This is the
smallest possible stand-in for the architecture doc's "exception-based
review" workflow; a real review UI is out of scope for a solo learning
build.

Usage: python eval/review.py data/synthetic_contracts/<file>.md [--out path.report.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.run_analysis import run_analysis  # noqa: E402
from shared.schemas import Finding, GapReport  # noqa: E402

_DECISIONS = {"a": "accept", "r": "reject", "e": "escalate"}
_DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def _print_finding(finding: Finding) -> None:
    print(f"\n[{finding.finding_id}] {finding.category} -- risk: {finding.risk_level}")
    print(f"  Contract ref : {finding.contract_reference.section}")
    if finding.baseline_reference:
        print(f"  Baseline ref : {finding.baseline_reference.doc} / {finding.baseline_reference.section}")
    elif finding.no_baseline_found:
        print("  Baseline ref : none (checked baseline, no coverage found)")
    else:
        print("  Baseline ref : none (UNVERIFIED -- no citation)")
    print(f"  Reason       : {finding.reason}")
    print(f"  Confidence   : {finding.confidence:.2f}  |  citation_verified: {finding.citation_verified}")
    print(f"  Recommended  : {finding.recommended_action}")


def review_findings(report: GapReport) -> None:
    if not report.findings:
        print("No findings to review -- nothing flagged for this contract.")
        return
    for finding in report.findings:
        _print_finding(finding)
        while True:
            choice = input("  Decision [a=accept / r=reject / e=escalate]: ").strip().lower()
            if choice in _DECISIONS:
                finding.reviewer_decision = _DECISIONS[choice]
                break
            print("  Please enter a, r, or e.")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python eval/review.py <path-to-contract.md> [--out path.report.json]")
        sys.exit(1)

    contract_path = Path(sys.argv[1])
    out_path = None
    if "--out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--out") + 1])
    if out_path is None:
        out_path = _DEFAULT_REPORTS_DIR / f"{contract_path.stem}.report.json"

    report = run_analysis(contract_path)
    review_findings(report)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    print(f"\nSaved reviewed report to {out_path}")


if __name__ == "__main__":
    main()
