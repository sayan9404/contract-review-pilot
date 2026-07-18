"""Streamlit UI for the contract-review pilot -- a thin local-only wrapper
around the existing P0-P4 pipeline. Not a new pipeline: every action here
calls straight into analysis/run_analysis.py, eval/review.py's decision
model, and the new analysis/chat.py, none of which know or care that a UI
exists.

Run: streamlit run app.py
"""
from __future__ import annotations

import hmac
import json
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

# Hosted platforms (e.g. Streamlit Community Cloud) provide the service
# secrets via st.secrets, not as environment variables. Mirror them into
# os.environ so shared/azure_clients.py's env-var path picks them up with no
# platform-specific code in the pipeline. Local dev has no secrets file, so
# st.secrets is empty/absent and the app falls through to Key Vault as
# before. Must run before any pipeline call that reads a secret.
try:
    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis.chat import answer_question  # noqa: E402
from analysis.run_analysis import run_analysis  # noqa: E402
from ingest.index import activate_version, list_active_documents, list_all_documents, supersede_document  # noqa: E402
from ingest.parse import TruncatedAnalysisError, parse_document_file  # noqa: E402
from ingest.promote import promote_to_baseline, slugify  # noqa: E402
from shared.schemas import GapReport  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent
_SAMPLE_CONTRACTS_DIR = _REPO_ROOT / "data" / "synthetic_contracts"
_REPORTS_DIR = _REPO_ROOT / "reports"
_DECISION_LABELS = {
    "accept": ":material/check_circle: Accept",
    "reject": ":material/cancel: Reject",
    "escalate": ":material/priority_high: Escalate",
}

st.set_page_config(page_title="Contract review pilot", page_icon=":material/fact_check:", layout="wide")


def _require_login() -> None:
    """Gate the whole app behind a single username/password.

    Credentials come from secrets/env (APP_USERNAME / APP_PASSWORD, bridged
    from st.secrets above), never hardcoded here -- so the password stays out
    of the public repo. hmac.compare_digest avoids leaking the answer via
    comparison timing. Called before anything else renders; on failure it
    draws the sign-in form and st.stop()s the rest of the script.
    """
    if st.session_state.get("authenticated"):
        return

    expected_user = os.environ.get("APP_USERNAME", "")
    expected_pw = os.environ.get("APP_PASSWORD", "")

    st.title(":material/lock: Sign in")
    st.caption("Contract review pilot -- authorized users only.")
    with st.form("login_form"):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary", icon=":material/login:")

    if submitted:
        if not expected_user or not expected_pw:
            st.error(
                "Login is not configured -- add APP_USERNAME and APP_PASSWORD to the "
                "app secrets.",
                icon=":material/error:",
            )
        elif hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_pw):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid username or password.", icon=":material/error:")
    st.stop()


_require_login()


def _run_analysis_on_bytes(name: str, content: bytes) -> GapReport:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / name
        tmp_path.write_bytes(content)
        return run_analysis(tmp_path)


@st.cache_data(ttl=30)
def _cached_all_documents() -> list[dict]:
    """Sidebar display only -- reruns on every interaction anywhere in the
    app, so this is cached briefly. The promote/disable/enable dialogs all
    call the ingest.index functions directly since they drive an actual
    decision and need fresh state."""
    return list_all_documents()


def _parse_bytes(name: str, content: bytes):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / name
        tmp_path.write_bytes(content)
        return parse_document_file(tmp_path)


@st.dialog("Add to baseline")
def _promote_dialog(source_name: str, source_bytes: bytes, contract_name: str) -> None:
    st.write(f"Promote **{source_name}** into the baseline knowledge base.")
    active_docs = list_active_documents()

    mode = st.segmented_control(
        "This document is:",
        ["A new baseline document", "A revision of an existing document"],
        default="A new baseline document",
        disabled=not active_docs,
    )

    document_id, supersedes = None, None
    if mode == "A new baseline document" or not active_docs:
        document_id = st.text_input("Document ID", value=slugify(contract_name))
    else:
        options = {f"{d['document_id']} (v{d['version']}, currently {d['source_doc']})": d["document_id"] for d in active_docs}
        label = st.selectbox("Supersedes", list(options))
        supersedes = options[label]
        st.caption(
            f"The current active version of **{supersedes}** will be marked superseded "
            "(kept for audit, excluded from retrieval) and replaced by this document."
        )

    if st.button("Confirm", type="primary", icon=":material/check:"):
        with st.spinner("Promoting to baseline..."):
            try:
                doc = _parse_bytes(source_name, source_bytes)
            except TruncatedAnalysisError as exc:
                st.error(f"Promotion stopped before touching the baseline: {exc}")
                st.stop()
            chunks = promote_to_baseline(doc, document_id=document_id, supersedes=supersedes)
        _cached_all_documents.clear()
        st.session_state["promotion_message"] = (
            f"Promoted '{source_name}' -- {len(chunks)} chunk(s) now active "
            f"under document_id '{supersedes or document_id}'."
        )
        st.rerun()


@st.dialog("Disable baseline document")
def _disable_dialog(document_id: str, version: int, source_doc: str) -> None:
    st.warning(
        f"Disable **{document_id}** v{version} (currently `{source_doc}`)?\n\n"
        "It will be excluded from all future analysis retrieval. Nothing is "
        "deleted -- its chunks stay in the index, marked superseded, for audit -- "
        "check \"Show disabled versions too\" in the sidebar to see it again and "
        "re-enable it later if needed.",
        icon=":material/block:",
    )
    if st.button("Confirm disable", type="primary", icon=":material/block:"):
        with st.spinner("Disabling..."):
            count = supersede_document(document_id)
        _cached_all_documents.clear()
        st.session_state["promotion_message"] = f"Disabled '{document_id}' -- {count} chunk(s) retired."
        st.rerun()


@st.dialog("Enable baseline document version")
def _enable_dialog(document_id: str, version: int, source_doc: str) -> None:
    current_active = next((d for d in list_active_documents() if d["document_id"] == document_id), None)
    if current_active:
        st.warning(
            f"Enable **{document_id}** v{version} (`{source_doc}`)?\n\n"
            f"This document_id currently has **v{current_active['version']}** active "
            f"(`{current_active['source_doc']}`) -- since only one version can be active "
            f"at a time, enabling v{version} will supersede v{current_active['version']} "
            "instead (kept for audit, excluded from retrieval).",
            icon=":material/swap_horiz:",
        )
    else:
        st.info(
            f"Enable **{document_id}** v{version} (`{source_doc}`)? Nothing else is currently active for it.",
            icon=":material/info:",
        )
    if st.button("Confirm enable", type="primary", icon=":material/check_circle:"):
        with st.spinner("Enabling..."):
            count = activate_version(document_id, version)
        _cached_all_documents.clear()
        st.session_state["promotion_message"] = f"Enabled '{document_id}' v{version} -- {count} chunk(s) now active."
        st.rerun()


_RISK_BADGE_COLORS = {"High": "red", "Medium": "orange", "Low": "blue", "Legal item": "violet"}


def _risk_badge(risk_level: str) -> str:
    color = _RISK_BADGE_COLORS.get(risk_level, "gray")
    return f":{color}-badge[{risk_level}]"


st.title(":material/fact_check: Contract review pilot")
st.caption(
    "Personal learning-scale pilot -- synthetic data only. Upload a Markdown, "
    "PDF, or Word contract, or pick one of the synthetic test contracts, then "
    "review the findings, coverage matrix, and ask follow-up questions."
)

with st.sidebar:
    if st.button("Sign out", icon=":material/logout:"):
        st.session_state.clear()
        st.rerun()

    st.header(":material/upload_file: 1. Choose a contract")
    sample_files = sorted(p.name for p in _SAMPLE_CONTRACTS_DIR.glob("*.md")) if _SAMPLE_CONTRACTS_DIR.exists() else []
    sample_choice = st.selectbox("Sample synthetic contract", ["-- none --", *sample_files])
    uploaded = st.file_uploader("...or upload your own", type=["md", "pdf", "docx"])

    source_name, source_bytes = None, None
    if uploaded is not None:
        source_name, source_bytes = uploaded.name, uploaded.getvalue()
    elif sample_choice != "-- none --":
        source_name = sample_choice
        source_bytes = (_SAMPLE_CONTRACTS_DIR / sample_choice).read_bytes()

    run_clicked = st.button(
        "2. Run analysis", disabled=source_name is None, type="primary", icon=":material/play_arrow:"
    )
    st.caption("Supports `.md`, `.pdf`, and `.docx` (see `ingest/parse.py`).")

    st.header(":material/inventory_2: Current baseline")
    show_all = st.toggle("Show disabled versions too")
    all_docs = _cached_all_documents()
    sidebar_docs = all_docs if show_all else [d for d in all_docs if d["status"] == "active"]
    if not sidebar_docs:
        st.caption("No baseline documents yet." if show_all else "No active baseline documents yet.")
    else:
        for d in sidebar_docs:
            active = d["status"] == "active"
            badge = ":green-badge[Active]" if active else ":gray-badge[Disabled]"
            row = st.columns([3, 1])
            row[0].markdown(f"{badge} **{d['document_id']}** (v{d['version']})  \n{d['source_doc']}")
            if active:
                if row[1].button("Disable", key=f"disable-{d['document_id']}-{d['version']}", icon=":material/block:"):
                    _disable_dialog(d["document_id"], d["version"], d["source_doc"])
            else:
                if row[1].button(
                    "Enable", key=f"enable-{d['document_id']}-{d['version']}", icon=":material/check_circle:"
                ):
                    _enable_dialog(d["document_id"], d["version"], d["source_doc"])

if run_clicked and source_name is not None:
    try:
        with st.spinner(f"Running parse -> rules -> retrieve -> generate -> report on {source_name} ..."):
            report = _run_analysis_on_bytes(source_name, source_bytes)
    except TruncatedAnalysisError as exc:
        st.error(f"Analysis stopped before running: {exc}")
        st.stop()
    st.session_state["report"] = report
    st.session_state["report_source"] = source_name
    st.session_state["report_source_bytes"] = source_bytes
    st.session_state["chat_history"] = []
    st.session_state.pop("promotion_message", None)

report: GapReport | None = st.session_state.get("report")

if report is None:
    st.info("Choose a contract in the sidebar and click **Run analysis** to get started.", icon=":material/info:")
    st.stop()

st.subheader(f":material/description: Report: {report.contract_name}")
summary = report.clause_inventory_summary
st.caption(
    f"Source: {st.session_state.get('report_source')}  |  "
    f"{summary.detected_clauses} clause(s) detected across {summary.total_pages} page(s), "
    f"{summary.tables} table(s)."
)

tab_findings, tab_coverage, tab_chat = st.tabs(
    [
        ":material/flag: Findings & review",
        ":material/checklist: Coverage matrix",
        ":material/chat: Ask about this report",
    ]
)

with tab_findings:
    if not report.findings:
        st.success("No gaps flagged for this contract.", icon=":material/check_circle:")
    for finding in report.findings:
        with st.container(border=True):
            cols = st.columns([3, 2])
            with cols[0]:
                st.markdown(f"**[{finding.finding_id}] {finding.category}**  {_risk_badge(finding.risk_level)}")
                st.write(finding.reason)
                st.caption(f"Recommended action: {finding.recommended_action}")
            with cols[1]:
                st.markdown(f"**Contract ref:** {finding.contract_reference.section or 'n/a'}")
                if finding.baseline_reference:
                    st.markdown(
                        f"**Baseline ref:** {finding.baseline_reference.doc} / "
                        f"{finding.baseline_reference.section or 'n/a'}"
                    )
                elif finding.no_baseline_found:
                    st.markdown("**Baseline ref:** none (checked, no coverage found)")
                else:
                    st.markdown("**Baseline ref:** :red[none -- UNVERIFIED, no citation]")
                citation_icon = ":material/verified:" if finding.citation_verified else ":material/error:"
                st.caption(
                    f"Confidence {finding.confidence:.2f}  |  "
                    f"rules force-flagged: {finding.rules_force_flagged}  |  "
                    f"citation verified: {finding.citation_verified} {citation_icon}"
                )

            decision = st.segmented_control(
                "Reviewer decision",
                options=["accept", "reject", "escalate"],
                format_func=lambda d: _DECISION_LABELS[d],
                default=finding.reviewer_decision,
                key=f"decision-{finding.finding_id}",
            )
            finding.reviewer_decision = decision

    action_cols = st.columns([1, 1, 3])
    with action_cols[0]:
        if report.findings and st.button("Save reviewed report", icon=":material/save:"):
            _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            out_path = _REPORTS_DIR / f"{report.contract_name}.report.json"
            out_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
            st.success(f"Saved to {out_path.relative_to(_REPO_ROOT)}", icon=":material/check_circle:")
    with action_cols[1]:
        if st.button("Add to baseline", icon=":material/library_add:"):
            _promote_dialog(
                st.session_state["report_source"], st.session_state["report_source_bytes"], report.contract_name
            )

    if "promotion_message" in st.session_state:
        st.success(st.session_state.pop("promotion_message"), icon=":material/check_circle:")

with tab_coverage:
    st.dataframe(
        [row.model_dump() for row in report.coverage_matrix],
        width="stretch",
        hide_index=True,
        column_config={
            "contract_area": st.column_config.TextColumn("Contract area"),
            "in_new_contract": st.column_config.CheckboxColumn("In new contract"),
            "in_baseline": st.column_config.TextColumn("In baseline"),
            "gap": st.column_config.CheckboxColumn("Gap"),
            "review": st.column_config.TextColumn("Review notes", width="large"),
        },
    )

with tab_chat:
    st.caption(
        "Answers are grounded only in this report's findings and coverage matrix -- "
        "not the raw contract text or a fresh baseline search."
    )
    for message in st.session_state.get("chat_history", []):
        with st.chat_message(message["role"]):
            st.write(message["content"])

    question = st.chat_input("Ask about this report...")
    if question:
        history = st.session_state.setdefault("chat_history", [])
        history.append({"role": "user", "content": question})
        with st.spinner("Thinking..."):
            answer = answer_question(report, history[:-1], question)
        history.append({"role": "assistant", "content": answer})
        st.rerun()
