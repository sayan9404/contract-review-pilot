"""Phase P3 step 2: deterministic critical-term scan, independent of the LLM
layer. A clause matching any configured critical term is force-flagged
regardless of what retrieval/generation decides downstream -- the safety net
behind the "critical miss rate must be zero" target from Technical
Foundation section 13.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from shared.schemas import ClauseInventoryEntry

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "critical_terms.json"

# Subset of critical terms that always route a finding to "Legal item" risk
# regardless of the LLM's own risk assessment or confidence -- matches the
# labelled test set's "always routes to legal regardless of confidence" rule
# for penalty/liability/termination-style clauses.
LEGAL_ROUTE_TERMS = {
    "penalty",
    "liquidated damages",
    "indemnity",
    "financial liability",
    "termination",
    "service credit",
}


def _load_terms() -> list[str]:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _compile(terms: list[str]) -> list[tuple[str, re.Pattern]]:
    return [(term, re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)) for term in terms]


@dataclass
class RuleMatch:
    clause_id: str
    matched_terms: list[str]

    @property
    def force_flagged(self) -> bool:
        return bool(self.matched_terms)

    @property
    def legal_override(self) -> bool:
        return any(term.lower() in LEGAL_ROUTE_TERMS for term in self.matched_terms)


def scan_clause(clause: ClauseInventoryEntry, terms: list[str]) -> RuleMatch:
    compiled = _compile(terms)
    matched = [term for term, pattern in compiled if pattern.search(clause.text)]
    return RuleMatch(clause_id=clause.clause_id, matched_terms=matched)


def scan_clauses(clauses: list[ClauseInventoryEntry]) -> dict[str, RuleMatch]:
    terms = _load_terms()
    return {clause.clause_id: scan_clause(clause, terms) for clause in clauses}
