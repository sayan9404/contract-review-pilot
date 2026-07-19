# Handoff / Progress Log

Last updated: 2026-07-19 -- app is LIVE on Streamlit Community Cloud with a
login gate; two baseline bugs found and fixed post-deploy. See the
2026-07-19 sections near the end. For a clean, standalone setup runbook an
L1 engineer can follow from zero, see `docs/SETUP_GUIDE.md`.

**If you're picking this up in a new session/machine and the conversation
history didn't carry over, read this file first — it's the source of truth
for what actually exists, not just what was discussed.**

## What this project is

Personal, learning-scale implementation of the AI-Assisted Contract Review &
Gap Analysis pipeline described in `../Contract_review.docx` (the finalized
proposal — one folder up from this repo) and the Architecture / Technical
Foundation source documents. Built solo on an Azure for Students subscription.
**Synthetic data only — never real client documents** (see `data/`).

The full approved implementation plan (phases P0-P4, decisions, repo layout,
verification steps) is preserved at `docs/implementation_plan.md` in this
repo — copied there specifically so it survives a machine change, since the
original only lived in this machine's local Claude Code plans folder.

## Status: Phase P0 — COMPLETE

- Repo scaffolded (config/, data/, shared/, scripts/ — see README.md for the
  full layout).
- `config/categories.json`, `config/critical_terms.json`, `config/chunking.json`
  written verbatim from the Technical Foundation doc.
- Synthetic baseline docs (`data/synthetic_baseline/`) and 3 synthetic test
  contracts (`data/synthetic_contracts/`) created, with a labelled ground-truth
  file at `data/labelled_test_set.json` for later evaluation (Phase P4).
- `shared/schemas.py` (Pydantic models: Finding, CoverageRow,
  ClauseInventorySummary, BaselineChunk, GapReport) — written and verified.
- `shared/azure_clients.py` — written (Key Vault + 4 service client getters).
- `scripts/check_connections.py` — written, **not yet run** (see below).
- Python venv created, `requirements.txt` installed, all imports verified.
- **Git is NOT installed** on the original dev machine — this repo was never
  put under version control. Worth doing `git init` + first commit once on
  the new machine, if git is available there (or install it).

## Status: Phase P1 — Azure provisioning — COMPLETE

### Resource inventory (all in resource group `rg-contractreview-pilot`, region **Southeast Asia**)

Important context: this subscription (Azure for Students) is policy-restricted
to exactly 5 regions: `centralindia`, `southeastasia`, `uaenorth`,
`koreacentral`, `malaysiawest`. `centralindia` was tried first and rejected —
`text-embedding-3-large` isn't deployable there under Standard or Global
Standard SKU. `southeastasia` worked for both models. If you ever need to
provision something new, stay in one of those 5 regions (check via Azure
Policy → Compliance on the subscription if you forget the list).

| Resource | Name | Notes |
|---|---|---|
| Resource Group | `rg-contractreview-pilot` | region: Southeast Asia |
| Azure OpenAI / Foundry project | `contractreview-pilot` | 2 model deployments (below) |
| — embedding deployment | `text-embedding-3-large` | Global Standard, Succeeded |
| — chat deployment | `gpt-5.4` (confirmed live 2026-07-14 — see P2 section below) | Global Standard |
| Storage Account | `stcontractreviewpilot` | Standard, LRS |
| — containers | `pilot-baseline`, `pilot-incoming`, `pilot-processed`, `pilot-reports` | all Private access |
| Document Intelligence | `docintel-contractreview-pilot` (confirm exact name on resume) | tier: F0 free (or S0 if F0 wasn't offered — confirm) |
| Azure AI Search | `search-contractreview-pilot` | tier: **Free** (no semantic ranker until upgraded to Basic — do that temporarily in Phase P3, then downgrade) |
| Key Vault | `kv-contractreview-pilot` | see secrets below |

### Key Vault secrets (all 6 confirmed created)

`storage-connection-string`, `docintel-endpoint`, `docintel-key`,
`search-endpoint`, `search-key`, `openai-endpoint`, `openai-key`

### Gotcha discovered — Key Vault permission model

The Key Vault uses **Azure RBAC** for data-plane access (not classic Access
Policies). Being subscription **Owner** does NOT grant secret read/write —
Owner is control-plane only. Had to explicitly add an IAM role assignment:
**"Key Vault Secrets Officer"** for the user's own account, scoped to the
vault. If this breaks again on setup (e.g. a fresh identity on the new
machine, or a service principal later), that's the role to grant.

### `.env`

Already created and pointed at the vault (`AZURE_KEY_VAULT_URL=...`). If
transferring only the git-tracked files (not a raw zip), remember `.env` is
gitignored and won't come along — recreate it from `.env.example` and the
vault's Overview page URL.

### P1 exit gate — DONE (2026-07-14, new machine)

On the new laptop: Azure CLI (v2.87.0) was already installed and `az login`
already completed (signed in as `Sayan.jana.9404@outlook.com`, subscription
"Azure for Students") by the time this session started.

Found and fixed one carry-over problem: **`.venv` had been copied from the
old machine instead of left behind**, so `pyvenv.cfg` still pointed at the
old machine's Python path (`C:\Users\ariji\...`) and every script failed
immediately with "did not find executable". Fixed by deleting `.venv` and
recreating it with the Python 3.10 install on this machine
(`C:\Users\Sayan\AppData\Local\Programs\Python\Python310\python.exe`), then
`pip install -r requirements.txt` (clean install, no errors).

Ran `scripts/check_connections.py` — **all 4 checks pass**:
`[OK] Key Vault + Storage connection string`, `[OK] Document Intelligence
client`, `[OK] AI Search client`, `[OK] Azure OpenAI client`. P1 exit gate
cleared — ready for Phase P2.

Chat deployment name (`gpt-5.4`) was confirmed live during P2 (see below).
Still outstanding, cosmetic only: the exact Document Intelligence resource
tier (F0 vs S0) was never double-checked against the Portal UI — confirm if
it matters for cost tracking.

### Still not done (not part of the P1 exit gate, but noted in P0)

- **Git still isn't initialized** in this repo (`git status` confirms no
  `.git`). Do `git init` + first commit when convenient — nothing in P0-P1
  depends on it, but it's the single biggest risk to losing work on the next
  machine move.

## Status: Phase P2 — Ingestion pipeline — COMPLETE (2026-07-14)

All 5 files built under `ingest/` and run end-to-end successfully against
`data/synthetic_baseline/`. Verified per the plan's P2 gate: clause-inventory
counts checked by hand against the actual baseline file content (all match,
nothing silently dropped), and the AI Search index was queried directly —
both keyword search (`"SIEM monitoring"`) and a real vector query (`"Is
there 24x7 support with a 15 minute P1 response time?"`) return correct,
relevant baseline chunks.

### Two real bugs found and fixed along the way (not just new code)

1. **`shared/azure_clients.py::get_openai_client()` was broken** — it used
   the classic `AzureOpenAI` client with `api_version="2024-10-21"` against
   an endpoint that turned out to be an **Azure AI Foundry *project*
   endpoint** (`https://contractreview-pilot-resource.services.ai.azure.com/api/projects/contractreview-pilot`),
   not a classic Azure OpenAI resource endpoint. That combination always
   fails with `"API version not supported"`. `check_connections.py` never
   caught this because it only *constructed* the client, never called it.
   Fixed by switching to the plain `OpenAI` client pointed at the resource's
   **v1 inference API** (`.../openai/v1/`, derived from the stored
   endpoint's host, api-version-less), and by making
   `check_connections.py`'s OpenAI check do a real `embeddings.create(...)`
   call so this class of bug can't hide again.
2. **Confirmed the real deployment names** (were unverified/guessed before):
   embedding deployment is `text-embedding-3-large`, chat deployment is
   **`gpt-5.4`** (confirmed by trial call — also note: this model rejects
   `max_tokens`, needs `max_completion_tokens` instead — relevant when P3
   builds the chat call in `analysis/generate.py`). Both constants now live
   in `shared/azure_clients.py` as `EMBEDDING_DEPLOYMENT` / `CHAT_DEPLOYMENT`.

### Design decisions made while building `ingest/`

- **Document Intelligence input format mismatch**: `prebuilt-layout` doesn't
  accept Markdown directly, and the synthetic baseline docs are `.md`/`.csv`
  (chosen for P0 readability, not for DI compatibility). Resolved by
  converting `.md` → minimal HTML (via the `markdown` package, `tables`
  extension) before calling DI — DI supports HTML natively and this still
  exercises the real Layout model (heading/table detection) rather than
  bypassing it. `.csv` is parsed directly with pandas instead of going
  through DI — it's already fully structured tabular data, DI adds nothing.
- **DI duplicates table cell content into `paragraphs`** — discovered by
  inspecting a real DI response on the SLA matrix table: every cell also
  shows up as a standalone paragraph. `ingest/parse.py` dedupes by exact
  content match so cells aren't chunked twice.
- **Reading order**: DI's `paragraphs` and `tables` arrays are separate, so
  true document order was reconstructed by sorting on each item's
  `spans[0].offset` (confirmed empirically — offsets line up with position
  in the source HTML).
- **Search document keys can't contain `.` or `::`** (AI Search key
  constraint: letters/digits/`_`/`-`/`=` only) — `chunk_id` generation in
  `ingest/chunk.py` sanitizes the source filename accordingly (caught by an
  actual `InvalidDocumentKey` error on first run, not by inspection).
- Index name: `contractreview-baseline`. Vector field dimensions: 3072
  (matches `text-embedding-3-large` output, confirmed live).

### What's next: Phase P3 (analysis pipeline)

Per `docs/implementation_plan.md`:

1. `analysis/parse_contract.py` — same DI Layout approach (reuse
   `ingest/parse.py`'s pattern) applied to one synthetic "new contract."
2. `analysis/rules.py` — regex/keyword scan against `config/critical_terms.json`.
3. `analysis/retrieve.py` — hybrid + semantic query against the baseline
   index from P2 (semantic reranking needs AI Search temporarily upgraded to
   **Basic** tier — remember to downgrade after testing).
4. `analysis/generate.py` — grounded prompt + `gpt-5.4` call, enforced JSON
   output matching `shared/schemas.py::Finding`. Remember: `max_completion_tokens`,
   not `max_tokens`.
5. `analysis/report.py` — assemble findings + coverage matrix + citations;
   enforce "no citation, no accepted finding."
6. `analysis/run_analysis.py` — orchestrates 1-5 end-to-end.

**Checkpoint (M3 gate)**: run against the synthetic contract with the
planted 24x7/P1 gap and confirm it's flagged HIGH risk with both citations
and a rules-layer force-flag. (The P2 vector-search smoke test above already
confirms retrieval surfaces the right baseline passages for this exact
scenario — P3 just needs to wire generation + rules on top.)

## Status: Phase P3 — Analysis pipeline — COMPLETE (2026-07-14)

All 6 files built under `analysis/` and run end-to-end against all 3
synthetic contracts via `python analysis/run_analysis.py <contract.md>`.

**M3 gate passed**: contract A's planted 24x7/P1 gap (Section 5.2) comes
back exactly as the architecture doc's running scenario expects — `risk_level:
"High"`, a real baseline citation (`SLA_matrix.md` + `SOW_v1.md` business-hours
clause), and `rules_force_flagged: true` from the deterministic critical-term
scan (`24x7`, `P1` both matched).

**Also checked against the rest of `labelled_test_set.json`**, not just the
M3 clause:
- Contract A: all 4 expected findings produced, none missed
  (`expected_critical_miss_count: 0` holds). Section 9.1 (Penalties) correctly
  gets forced to `risk_level: "Legal item"` regardless of the model's own
  confidence, via the new `rules.py::LEGAL_ROUTE_TERMS` override.
- Contract B (clean control case): **zero findings** — correct, since a
  false positive here is exactly what the false-positive-rate metric in
  Phase P4 will penalize.
- Contract C (no-baseline-coverage case): both expected findings produced
  (Disaster recovery, Resource obligations), correctly citing "no baseline
  coverage found" for the DR clause.

Two things worth knowing before P4 builds the scorecard — not bugs, just
where the two layers (deterministic rules vs. LLM judgment) diverge from the
hand-authored labels:
1. **Category/risk-level judgment sometimes differs from the hand-labeled
   ground truth.** E.g. contract A Section 5.3 (SIEM monitoring) came back
   as category `"Security & compliance"` / `High` where the label says
   `"Monitoring"` / `Medium` — both are defensible reads of the same clause.
   This is exactly what Phase P4's metrics are for; P3 isn't expected to
   hand-match every label.
2. **The critical-terms rules layer only catches literal phrasing.**
   `config/critical_terms.json` has `"within 15 minutes"` and `"named
   resource"` as exact phrases, but the contracts say "15-minute response
   SLA" and "a named, dedicated on-site resource" — close paraphrases that
   don't literally substring-match, so `rules_force_flagged` is `false` on
   those clauses even though `critical_terms_expected` in the labelled set
   lists them. The LLM+retrieval layer still catches these clauses as gaps
   independently (confirmed in both cases above) — this is the intended
   division of labor: rules catch verbatim critical terms deterministically,
   the semantic layer catches paraphrases. Don't "fix" this by loosening the
   regex to fuzzy-match; that would defeat the point of having a
   deterministic layer at all.

### Design decisions made while building `analysis/`

- **Finding has no `gap` field** (checked `shared/schemas.py` — it doesn't).
  A `Finding` object is only ever created for an actual flagged issue.
  `analysis/generate.py` returns an internal `ClauseAssessment` (not a
  `Finding`) for *every* clause, including non-gap ones; `report.py` decides
  which become `Finding`s (gap=true, or rules-force-flagged even if the LLM
  said no-gap) and uses the full assessment list for every category's
  `CoverageRow`, gap or not.
- **Citations can't be hallucinated by construction, not just by prompt
  wording**: the model never outputs a baseline document/section name
  itself — it can only point at a 1-based index into the numbered passages
  `retrieve.py` actually returned, and `generate.py` resolves the real
  `source_doc`/`section`/`page` server-side from that index. Combined with
  strict JSON-schema structured output (`response_format: json_schema`,
  `strict: true`), this is the actual mechanism behind "no citation, no
  accepted finding," not just an instruction the model could ignore.
- **`citation_verified`** (used by `report.py::_citation_verified`) is
  `True` only if: rules force-flagged it (deterministic evidence, no LLM
  citation needed), or the model explicitly said "checked, nothing found,"
  or there's a real index-resolved baseline citation. Anything else would be
  marked unverified — in practice this never fired across all 3 test
  contracts, meaning nothing hallucinated a citation.
- **Semantic ranking works on the Free AI Search tier**, contrary to what
  the plan assumed (`docs/implementation_plan.md` said it'd need a temporary
  Basic-tier upgrade) — confirmed live. `analysis/retrieve.py` still has a
  defensive fallback to plain hybrid search on any `HttpResponseError`, in
  case that changes.
- Clause extraction groups by heading (one clause per `## Section X.Y`),
  distinct from `ingest/chunk.py`'s token-window chunking used for the
  baseline side — contracts need one clause per logical section to match how
  `labelled_test_set.json` references them (`"clause_ref": "Section 5.2"`),
  not arbitrary token windows.

## Status: Phase P4 — Evaluation harness — COMPLETE (2026-07-14)

Built `eval/metrics.py`, `eval/run_eval.py`, `eval/review.py`. Ran
`python eval/run_eval.py` over all 3 contracts against
`data/labelled_test_set.json`.

**The real MVP exit-gate targets weren't in this repo** -- `HANDOFF.md`/
`docs/implementation_plan.md` only said "see the proposal's targets table"
without the numbers. Pulled the actual table out of `../Contract_review.docx`
(section 09, Recommendation/Ask) by unzipping it and stripping the
`word/document.xml` markup -- no `python-docx` needed, the docx is just a
zip of XML. For the record, the real targets:

| Metric | Target |
|---|---|
| Clause extraction quality (clean docs) | 90%+ |
| Citation accuracy | 90%+ findings with correct source reference |
| Critical miss rate (high-risk SLA/scope) | Zero |
| False positive rate | Below ~25-30% |
| First-pass review time | 1-2 days to a few hours (human-process, not automatable) |
| Reviewer satisfaction | 4/5 or higher (human-process, not automatable) |

**Scorecard result, pooled across all 3 contracts — all 4 automatable
targets PASS**:

| Metric | Result | Target | Status |
|---|---|---|---|
| Clause extraction quality | 100% (9/9) | 90%+ | PASS |
| Citation accuracy | 100% (6/6) | 90%+ | PASS |
| Critical miss rate | 0% | Zero | PASS |
| False positive rate | 0% | <25-30% | PASS |
| Retrieval Recall@K (informational, not in the proposal's table) | 67% (2/3) | none set | — |

The one interesting number is Recall@K's 2/3: for contract C's "named,
dedicated on-site resource" clause, top-3 hybrid+semantic retrieval never
surfaced `skills_matrix.csv` (which shows 0 available Security Analysts /
1 L3 engineer -- contextually relevant per the label) even though it's in
the index. Verified this isn't a scoring bug by calling `retrieve()`
directly: the CSV's actual content ("L2 Support Engineer", "SIEM
Monitoring", headcount numbers) just doesn't lexically or semantically
overlap much with "on-site resource" in a 7-chunk baseline this small. A
real, known limitation of a tiny corpus, not something to fix by hacking
the scorer -- would need either a larger/denser baseline or query
expansion to matter in practice, neither of which is warranted at this
scale. Recall@K isn't in the proposal's own exit-gate table for a reason
(it's an engineering-only diagnostic), so this doesn't block anything.

**`eval/review.py`** (the human-review-loop stand-in) was smoke-tested by
piping canned answers (`a`/`e`/`a`/`r`) instead of live keyboard input, then
confirming the saved JSON (`reports/*.report.json`, matches the existing
`.gitignore` pattern) actually persisted those decisions into each
`Finding.reviewer_decision`. Confirmed working -- run it interactively for
real use: `python eval/review.py data/synthetic_contracts/<file>.md`.

## Status: Local Streamlit UI — COMPLETE (2026-07-15)

Not part of the original P0-P4 plan (checked `Contract_review.docx` -- a
management dashboard is explicitly a **Phase 3 (Scale)** item, not this MVP
pilot), added because the user wanted to actually click through the tool
rather than read CLI/JSON output. Scope was narrowed on purpose before
building, via two decisions:
- **Chat is grounded on one already-generated report only** (findings +
  coverage matrix), not a fresh RAG chat over the whole baseline. No new
  retrieval pipeline -- `analysis/chat.py` just formats the existing
  `GapReport` as context and answers from that alone, same "don't answer
  from outside knowledge" rule as `analysis/generate.py`.
- **Local only** (`streamlit run app.py`), no deployment/auth work.

Built:
- `analysis/chat.py` -- report-grounded Q&A, reuses `az.get_openai_client()`
  / `az.CHAT_DEPLOYMENT`, same prompt-injection stance as generate.py
  (report data + questions are DATA, not instructions).
- `app.py` -- sidebar contract picker (sample dropdown from
  `data/synthetic_contracts/` or upload a `.md` file) -> runs
  `analysis/run_analysis.py` -> three tabs: Findings (with the same
  accept/reject/escalate decision model as `eval/review.py`, plus a save
  button writing to `reports/*.report.json`), Coverage matrix, and Ask
  (chat).
- Added `streamlit` and `markdown` (the latter was already installed in P2
  but never added to `requirements.txt` until now -- caught while editing
  the file) to `requirements.txt`.

**Verified working**, not just "written": no browser tool exists in this
environment, so used Streamlit's own `AppTest` headless test harness
(`streamlit.testing.v1.AppTest`) to actually drive the app -- selected
`contract_A_acme_msa_2026.md` from the sidebar, clicked "Run analysis",
confirmed F001-F004 rendered, then asked the chat "Why was Section 5.2
flagged?" and got back a correct answer citing F001 and the real gap
(24x7/15-min vs. the business-hours/next-business-day baseline). Also
caught and fixed a real deprecation before it caused a break: `st.dataframe`'s
`use_container_width` param's removal date (2025-12-31) had already passed
as of today -- switched to `width="stretch"`.

**To try it yourself**: `streamlit run app.py`, then open the local URL it
prints.

### Baseline versioning / promotion added (2026-07-16)

User's workflow: upload contract 1 -> promote it as the baseline (nothing
existed yet). Later, a *revised* contract 2 arrives -> analyze it against
the baseline -> optionally promote it too. The open design question: does
promoting contract 2 mean the baseline now has v1 *and* v2 active
simultaneously (risk: retrieval surfaces both old and new SLA terms for the
same query, model can't tell which is current), or does v2 replace v1?

Discussed before writing code (see conversation) and settled on the
standard document-versioning pattern used in real contract-ops/compliance
RAG systems: **every baseline document gets a `document_id` + `version` +
`status` (active/superseded)**. A revision shares its predecessor's
`document_id`, bumps `version`, and flips the old version's chunks to
`status="superseded"` -- kept in the index for audit (`what did the
baseline say when contract X was reviewed`), just excluded from retrieval
by a `status eq 'active'` filter. A genuinely new/unrelated document (not a
revision of anything) gets its own fresh `document_id` and coexists. The
human always states which case it is at promotion time -- never inferred.

Built:
- `shared/schemas.py::BaselineChunk` -- added `document_id`, `version`,
  `status` fields.
- `ingest/index.py` -- matching filterable index fields, plus
  `supersede_document(document_id)` (metadata-only partial update, flips
  matching active chunks to superseded -- doesn't touch text/embedding, and
  nothing gets deleted) and `list_active_documents()` (one row per active
  `document_id`, powers the UI's supersede-picker and the sidebar's
  "current baseline" view).
- `ingest/promote.py` (new) -- `promote_to_baseline(doc, document_id=... |
  supersedes=...)`, the one function both paths go through. Exactly one of
  `document_id` (new doc) or `supersedes` (revision) must be given --
  enforced, not just documented.
- `analysis/retrieve.py` -- both the semantic and hybrid search calls now
  filter `status eq 'active'`, so superseded chunks are structurally
  invisible to analysis, not just conventionally ignored.
- `ingest/run_ingest.py` -- refactored to call `promote_to_baseline` instead
  of doing its own chunk/embed/push, so the 4 original baseline docs
  (`SOW_v1.md` etc., indexed before this feature existed) get backfilled
  with real `document_id`/`version=1`/`status=active` instead of missing
  the fields entirely. Re-ran it -- confirmed via `list_active_documents()`.
- `app.py` -- sidebar "Current baseline" table (cached 30s -- it reruns on
  every interaction anywhere in the app, so it's not hitting Search on every
  keystroke in the chat box); an "Add to baseline" button on the Findings
  tab opens an `@st.dialog` asking "new document, or a revision of
  [dropdown of active docs]?", then calls `promote_to_baseline` with the
  resolved args.

**Also found and fixed a real, unrelated latent bug while in `ingest/index.py`**:
`ensure_index()` referenced `_SEMANTIC_CONFIG`, a name that only existed
before the P3 rename to `SEMANTIC_CONFIG_NAME` -- the rename edit back then
only caught the definition line, not this usage. `ensure_index()` hadn't
been called since that rename, so the `NameError` was never triggered until
now, when this feature needed to call it again to push the new index
fields.

**Verified**:
- Direct test of both `promote_to_baseline` paths with live Azure calls: a
  synthetic "SOW v2, revised to 24x7" promoted with `supersedes="sow_v1"`
  correctly bumped it to version 2/active, flipped the 3 v1 chunks to
  superseded (confirmed still present in the index, not deleted), and a
  retrieval query for "support hours" afterward returned *only* the v2
  content -- the old "business hours" text never surfaced. Then cleaned up
  the test data (deleted the throwaway v2 chunks, restored `sow_v1` to
  v1/active) so the real baseline wasn't left in a test state.
- The "new document" path was exercised (non-throwaway) via re-running
  `ingest/run_ingest.py` itself -- all 4 baseline docs correctly backfilled.
- `app.py` starts clean and the sidebar's baseline table renders correctly
  via `AppTest`.
- **Known verification gap**: `AppTest` (this Streamlit version) has no
  element-tree support for driving `@st.dialog` contents -- confirmed by
  checking the testing module directly, not assumed. Clicking "Add to
  baseline" to *open* the dialog was confirmed not to throw, but the
  dialog's own radio/selectbox/confirm-button flow could only be verified
  by code review, not driven end-to-end the way the rest of the app was.
  Worth clicking through this one manually before trusting it fully.

### Manual "disable baseline document" added (2026-07-16)

User wanted a way to retire a baseline document without necessarily
promoting a replacement (e.g. it's wrong/outdated and there's nothing to
supersede it with yet). No backend change needed -- `ingest/index.py`'s
`supersede_document()` (built for the promotion-supersede path above)
already does exactly this: flip a document_id's active chunks to
superseded, kept for audit, nothing deleted. Just needed a UI trigger.

Added to `app.py`: each row in the sidebar's "Current baseline" list now has
a **Disable** button, opening an `@st.dialog` confirmation (this is
destructive-ish -- it stops the document from being retrievable in all
future analysis -- so it's gated behind a confirm click, not a bare
one-click action) that calls `supersede_document` directly. Explicitly out
of scope: no "re-enable" action -- said so in the dialog's own copy, since
un-doing a disable currently means promoting a fresh revision, not a toggle.

**Incident during testing, resolved**: while verifying this, a single
`supersede_document('skills_matrix')` call was followed (after Azure
Search's normal indexing propagation delay) by **all 4** baseline documents
showing as superseded, not just the one intended -- i.e. the whole baseline
briefly went dark. Took this seriously and ran it to ground rather than
patching over it:
- Re-ran `ingest/run_ingest.py` immediately to restore all 4 to
  version=1/active (confirmed via `list_active_documents()`).
- Reproduced the *isolated* call in an ordered, single-step script (dump
  state -> call `supersede_document('skills_matrix')` -> dump state
  immediately -> wait -> dump state again): behaved **correctly** --
  only skills_matrix's one chunk flipped, the other 3 documents untouched.
- Reproduced the *AppTest UI click path* (open the Disable dialog via the
  sidebar button, same sequence as before) with **no live Streamlit server
  running**: also behaved correctly -- clicking to open the dialog doesn't
  touch the backend at all (only the dialog's own inner "Confirm disable"
  button does, and AppTest can't drive that -- same limitation noted for
  the promotion dialog above).
- The one variable present during the original incident and absent from
  both clean reproductions: **a live `streamlit run` background server that
  was still running while `app.py` was being actively edited** (several
  `Edit` calls to add the disable dialog/sidebar changes happened while
  that old process, from the PDF/DOCX work earlier, was still up). Its
  file-watcher likely replayed stale session/widget state across a
  mid-edit reload. Restarting it fresh *after* edits finish, rather than
  editing underneath a running instance, didn't reproduce the issue.
- Root cause isn't 100% nailed down (didn't dig into Streamlit's
  file-watcher/session internals further), but the actual backend function
  is now verified correct in isolation twice, and the practice going
  forward is: **don't leave `streamlit run` up while editing the file it's
  serving; restart it fresh once edits are done and verified.**
- Data integrity: nothing was permanently lost either way -- the whole
  point of soft-supersede-not-delete is that even the corrupted state was
  recoverable by re-running `run_ingest.py`, which is exactly what happened.

### "Show disabled versions" + re-enable/rollback added (2026-07-16)

User tried the Disable feature live in the app -- disabled all 4 original
synthetic baseline docs while testing, and separately promoted a real PDF
(`Azure_Enterprise_Cloud_Modernization_Agreement.pdf`) as a new baseline
document (**note**: worth confirming this isn't real client data --
filename doesn't match the forbidden Metso/Inomotics/Primark names, but
double-check before this goes further, per the repo's synthetic-only
policy). Once disabled, a document dropped out of the sidebar's active-only
list with no way to see it again or bring it back -- user asked for both.

**Important process note for future sessions**: while diagnosing this, an
early `list_all_documents()` check revealed the *actual current index
state* differs from anything I'd set up -- this is the user's real,
intentional activity from using the live app, not leftover test data. Did
**not** run `ingest/run_ingest.py` or touch their state at all this round;
verified the new backend functions (`activate_version` specifically) using
a fully throwaway `zzz_test_doc` document_id, then deleted it entirely
afterward. Confirmed their 5 real documents were untouched before, during,
and after.

Built:
- `ingest/index.py` -- refactored `supersede_document` onto a shared
  `_update_status(filter_expr, status)` helper; added
  `activate_version(document_id, version)` (supersedes whatever's currently
  active for that document_id first -- a no-op if nothing is -- then
  activates the requested version, preserving the one-active-version
  invariant) and `list_all_documents()` (every `(document_id, version)`
  ever pushed, active or superseded -- the full history).
  `list_active_documents()` is now just a filter over `list_all_documents()`.
- `app.py` -- sidebar gets a "Show disabled versions too" checkbox; checked,
  it lists every version with a status badge, "Enable" on disabled ones
  (opens a confirm dialog -- warns if this will supersede a *different*
  currently-active version of the same document_id) and "Disable" on active
  ones (unchanged from before). Renamed the sidebar's cache from
  `_cached_active_documents` to `_cached_all_documents` since it now backs
  both views.

**Verified**: `activate_version` tested with a real promote-then-rollback
cycle on the throwaway test document (v1 active -> promote v2 as
supersedes -> v1 superseded/v2 active -> `activate_version(.., 1)` -> v1
active/v2 superseded, confirmed via direct reads at each step) -- correct
version-toggle behavior, single-active-version invariant held throughout.
`AppTest` confirms the sidebar checkbox toggles between showing 1 button
(Disable, for the 1 real active doc) and 6 buttons (1 Disable + 4 Enable,
matching the real current state exactly) with no exceptions. Same known gap
as the other two dialogs: `AppTest` can't drive `@st.dialog` internals, so
the Enable dialog's own confirm-button path is verified by direct backend
testing + code review, not a fully driven UI click-through.

### Critical bug found and fixed: Document Intelligence silently truncates PDFs to 2 pages (2026-07-16)

User ran a real 9-page contract through the app and got 5 clauses across 2
pages back -- their friend reviewed the output, correctly identified the
severity (coverage matrix showing 16/17 categories as "Not addressed" when
most were simply never ingested -- "not addressed" was indistinguishable
from "not ingested", the worst possible failure mode for a review tool),
and guessed the mechanism was a hardcoded page-limit bug in the ingestion
code.

**Verified independently rather than taking the diagnosis on faith**:
checked `ingest/parse.py` for any hardcoded slice/limit -- none exists.
Generated a fresh throwaway 9-page PDF with unique per-page text and ran it
through the real code path: same result, 2 of 9 pages. Called the Document
Intelligence API directly, bypassing all of this project's code: **the API
itself only returns 2 pages**, with no error or warning field indicating
why. This is undocumented-in-the-response but well-known behavior of Azure
Document Intelligence's **Free (F0) tier** -- silently caps analysis at 2
pages per document. This resource was provisioned on F0 back in Phase P1
(see above) and never noticed because every P0-P4 test document was 1 page;
this was the first real multi-page document to hit the pipeline.

**The friend's guess at mechanism was wrong (not a code bug -- an Azure
resource tier limit) but everything else was right**, including the fix
suggestion ("fail loudly instead of silently"). Asked the user how to
handle it: upgrade to S0 (removes the cap, small real cost) vs. keep F0 and
batch PDFs into 2-page chunks in code (free, meaningfully more fragile).
User chose **upgrade to S0** -- I can't do this myself (confirmed again:
`az cognitiveservices account show` on this resource group returns
`ResourceGroupNotFound` for the currently logged-in identity, consistent
with the ARM-visibility gap found back in Phase P2). **User needs to do
this themselves** in the Portal: `docintel-contractreview-pilot` -> Resource
Management -> Pricing tier -> S0.

Built regardless of the tier decision (defends against this class of bug
happening silently again, on any tier, for any reason):
- `ingest/parse.py::TruncatedAnalysisError` + a check in `parse_office_file`
  -- compares DI's returned page count against the PDF's *real* page count
  (via `pypdf`, a new dependency) and raises a clear, actionable error
  instead of silently returning a truncated `ParsedDocument`.
- `app.py` -- both the "Run analysis" and "Add to baseline" flows catch
  this and show `st.error(...)` with the real explanation, instead of a raw
  traceback. Promotion is blocked entirely if the source document would
  truncate -- a truncated document must never reach the baseline.

**Important follow-up the user still needs to do**: the currently active
baseline document (`azure_enterprise_cloud_modernization_agreement`,
promoted before this fix existed) was almost certainly promoted while
truncated to 2 pages too. Once the tier is upgraded, **re-run analysis and
re-promote it** -- the current baseline is likely incomplete until that
happens.

**Decision: S0, not a free-tier workaround.** User asked about staying on
F0 (batch PDFs into 2-page chunks through DI, or skip DI for PDFs entirely
and hand-roll parsing with pypdf/pdfplumber). Both are real options and I
described their tradeoffs, but recommended against both once asked for the
industry-best-practice call: batching silently breaks any table spanning a
2-page boundary; DIY local parsing regresses on `docs/implementation_plan.md`'s
own Phase P0 decision to never build a local/alternate processing path and
always call the real production-equivalent service. At Layout's real cost
(~$1.50/1,000 pages) neither workaround's accuracy loss is worth avoiding a
cost that's negligible at this pilot's scale. Landed on: **upgrade to S0 +
finally set up the budget alert** that was flagged as a P1 to-do back at
the start of this project and never done -- that's the actual missing
piece, not a code workaround. Both steps require the Portal (no ARM access
from here, same gap as above): Pricing tier on
`docintel-contractreview-pilot`, and a Cost Management budget on the
subscription or `rg-contractreview-pilot`.

**User upgraded to S0 in the Portal.** Verified with the same throwaway
9-page test PDF used to originally catch this bug: now correctly returns
all 9 pages with accurate per-page content, no `TruncatedAnalysisError`.
Confirmed against the live service directly, not just trusting the
Portal's (oddly-worded) success notification. **Still outstanding**:
budget alert not yet set up (user's own to-do in Cost Management); and the
active baseline document is still the pre-fix truncated 2-page version --
needs re-running through analysis and re-promoting now that the tier
supports the real document length.

### Second bug found the same day: table-of-contents collision was silently eating real section headings (2026-07-16)

With the page cap fixed, the user's friend did a second review and noticed
the finding count didn't move (5 findings before the fix, still 5 after --
despite going from 2 pages of source material to 9). Friend's hypothesis
was a hardcoded cap (`top_k=5`, a `[:5]` slice, etc.).

**Ruled that out by direct code inspection first**: grepped all of
`analysis/` for any numeric limit -- the only `top_k` in the codebase is
`analysis/retrieve.py`'s `TOP_K=3`, which controls baseline passages
retrieved *per clause* for citations, unrelated to how many clauses get
extracted from the contract. No cap exists anywhere.

**Found the real cause by asking the user to run a new diagnostic script**
(`scripts/diagnose_headings.py`, one-off, not part of the pipeline) against
their actual PDF and share the raw output -- confirmed empirically instead
of guessing again. The output showed Document Intelligence correctly
tagging all 22 real section headings (`1. Purpose` through `21. Sign-Off`,
`CONFIDENTIALITY NOTICE`, `REVISION NOTE`, etc.) as `SECTION_HEADING` --
so the original "heading detection gap" theory from earlier in this session
was wrong. The actual bug: `ingest/parse.py::_to_parsed_document()`'s
table/paragraph deduplication (written back in Phase P2, intended to drop
a table's cell content when DI also emits it as a standalone paragraph)
compared **text values**, not physical position. This document's Table of
Contents is itself a detected table listing every section title as a cell
value (`"1. Purpose"`, `"2. Project Overview"`, ...) -- so every real
heading later in the document with that exact same text got wrongly
treated as a "duplicate" of the TOC's cell and silently dropped. Only the
3 headings whose text never appears in any table
(`CONFIDENTIALITY NOTICE`, `REVISION NOTE`, `Table of Contents`) survived,
which is why the clause count stayed pinned regardless of how many pages
got ingested.

**Fix**: replaced the value-based `set` of cell text strings with a
position-based check using `DocumentTableCell.spans` (confirmed this field
exists by inspecting the SDK model directly) -- a paragraph is only
dropped as a table-cell duplicate if its own span *overlaps* a real
cell's span, not merely if the text happens to match. See
`ingest/parse.py::_is_table_cell_occurrence()`.

**Verified**: reproduced the exact collision pattern in a throwaway test
PDF (a TOC table listing "1. Purpose" / "2. Overview" / "3. Commercials" as
cells, then those same three headings for real later in the document) --
confirmed broken before the fix (would have dropped all 3), confirmed
fixed after (all 3 survive, each becomes its own clause). Then ran a
regression check against the existing P2/P3 test data
(`data/synthetic_baseline/`, `data/synthetic_contracts/`) using local
parsing only, no live index writes -- contract A/B/C clause counts are
unchanged from the original Phase P3 validation (4/3/2), confirming the
fix doesn't regress the simpler documents that don't have this collision.

Deliberately did **not** re-run `ingest/run_ingest.py` against the live
index to "fully" verify -- that would reactivate the user's 4 synthetic
baseline documents (currently superseded, by their own choice, while
testing with a real document) without asking first. Left the live baseline
state exactly as the user left it.

**Next step for the user**: re-run analysis on the real 9-page contract
again -- clause count should now be close to the real ~22 sections instead
of 5, and the coverage matrix should populate correctly across categories
instead of showing false "Not addressed" for sections that are actually in
the document. `scripts/diagnose_headings.py` can stay in the repo as a
reusable diagnostic for this class of issue, or be deleted -- it's not
wired into the pipeline either way.

**Verified**: the throwaway 9-page test PDF correctly raises
`TruncatedAnalysisError` when called directly, and the same file pushed
through the actual Streamlit upload button (via `AppTest`) shows the clean
`st.error` message with no unhandled exception -- confirmed end to end
through the real UI path, not just the underlying function.

### Root cause found for the friend's "same clause, different verdict across runs" finding (2026-07-17)

Friend did a third pass and found something more serious than category
instability: **the same clause's gap/no-gap verdict itself flipped**
between runs. Traced it to "6. Roles & Responsibilities" specifically --
in one run the LLM correctly matched it against the real baseline
responsibility table (no gap); in another it only retrieved a passage that
"merely identifies the same section heading" and concluded gap=true. The
friend correctly verified Section 6 is byte-identical between the two real
PDFs, so this was a genuine false positive, and correctly hypothesized
retrieval nondeterminism (ANN/embedding jitter) as the likely mechanism.

**Confirmed the concrete cause, not just the symptom**: queried the live
index directly for that section and found **two separate chunks**, not
one:
- one chunk: `"6. Roles & Responsibilities Client (...) Service Provider
  (...) CONFIDENTIAL - ... Page 4 of 9 Cloud Modernization & Migration
  Agreement AZURE ENTERPRISE CLOUD MODERNIZATION PROGRAM"` -- the heading,
  a stray fragment of the table's own header row, and page footer/header
  boilerplate, all glued together
- another chunk: the actual responsibility table content

Two things caused this:
1. The table spans a page break (page 4 -> page 5). Document Intelligence
   extracted the header row as a loose paragraph on page 4, separate from
   the table object it detected on page 5 -- `ingest/chunk.py` always
   flushed whatever preceded a table into its own chunk, so this stray
   fragment became a standalone, near-empty, retrievable chunk sitting
   right next to the table's real content.
2. **`ingest/parse.py` never filtered `PAGE_HEADER`/`PAGE_FOOTER`/`PAGE_NUMBER`-role
   elements** -- despite Document Intelligence explicitly tagging them so
   consumers can exclude them, they flowed straight into the element stream
   as ordinary paragraphs, inflating that stray fragment with repeating
   boilerplate and making it look more substantial than it was.

With two near-duplicate chunks (one mostly noise, one the real content)
sitting at similar embedding-similarity distance from the query, ordinary
run-to-run jitter in the embedding API (well-documented, not something any
caller controls) was enough to occasionally rank the noise chunk into the
top-3 window instead of, or ahead of, the real one -- exactly matching the
friend's hypothesis, just with the concrete mechanism identified.

**Fixed both causes**:
- `ingest/parse.py::_to_parsed_document()` now skips `PAGE_HEADER`/`PAGE_FOOTER`/`PAGE_NUMBER`
  role elements entirely -- they never become `ParsedElement`s.
- `ingest/chunk.py`: when a table follows other content in the same
  section, the preceding buffer now merges into the table's own chunk
  whenever the combination still fits `max_tokens`, instead of always
  splitting them into two chunks. (First tried a "merge if the buffer is
  under N tokens" heuristic -- didn't actually fix this case, since the
  stray header-row fragment plus page furniture pushed it well past any
  reasonable trivial-fragment threshold. The token-budget-fit version is
  the more principled, general fix -- no magic number, and it directly
  addresses *why* a fragment ends up looking non-trivial in the first
  place instead of just tuning around it.)

**Verified**: same section now produces exactly one coherent chunk
combining the heading, the (now correctly filtered) short intro, and the
full table. Confirmed via the full chunk list for the real document (29
clean chunks, all well-formed, no orphan fragments) and regression-checked
against all 4 synthetic baseline docs (`SLA_matrix.md` improved from 2
chunks to 1 for the same reason) and all 3 synthetic contracts' clause
extraction (unchanged: 4/3/2, matching original P3 validation -- this
fix only touches baseline-side chunking, contract-side clause extraction
uses separate logic in `analysis/parse_contract.py` unaffected by it).

**Important limitation to flag**: this fix doesn't retroactively repair
already-indexed chunks. The user's currently active baseline document
(`azure_enterprise_cloud_modernization_agreement`) was promoted *before*
this fix and still has the old fragmented chunking live in the index --
**it needs to be re-promoted** (Add to baseline -> revision of itself) to
actually pick up the corrected chunks. Recommending this strongly since
it's the direct fix for the exact bug being chased, but not doing it
myself -- same reasoning as every other baseline-state decision this
session: it's a real, visible change to their live data that they should
trigger deliberately, not something that happens silently as a side effect
of a code fix.

### Hosting: pivoted to Streamlit Community Cloud (free); code is ready, deploy is user-side (2026-07-18)

User wanted to host cheaply on "my Azure". Investigated and hit a hard
blocker: **the "Azure for Students" subscription (the only one this
machine's `az login` can see) is spending-limit locked -- read-only.**
`az webapp create` failed with `ReadOnlyDisabledSubscription`; `az account
list` reports it "Enabled" but writes are blocked, which is the classic
Azure-for-Students out-of-credit state (also why the existing
`azragchatbot-app` on the B1 plan was `AdminDisabled`). The contract-review
DATA services (Key Vault, the S0 Doc Intelligence, Search, OpenAI) are in a
DIFFERENT, still-active subscription/tenant ("DEFAULT DIRECTORY") that this
`az login` can't reach -- reachable only via their data-plane keys.

Given the "less cost" priority and the dead Students sub, user chose
**Streamlit Community Cloud (free)**. The app is fully portable -- it talks
to the Azure data services over HTTPS with keys, so it doesn't matter that
it's hosted off-Azure.

**Code changes made to support hosting (all verified, backward-compatible):**
- `shared/azure_clients.py::get_secret` now reads an env var first
  (`storage-connection-string` -> `STORAGE_CONNECTION_STRING`, etc.) and
  only falls back to Key Vault if unset. So a hosted app needs NO Key Vault
  access and NO `az login`/managed identity -- just the 7 secret values as
  env vars. Local dev sets none, so it still uses Key Vault via
  DefaultAzureCredential exactly as before. Both paths unit-tested.
- `app.py` bridges `st.secrets` -> `os.environ` at startup (guarded
  try/except; a no-op locally where no secrets file exists). This is what
  makes the env-var path work on Streamlit Cloud, whose secrets arrive via
  `st.secrets`, with zero platform-specific code in the pipeline. Verified
  end-to-end via AppTest (which loads `.streamlit/secrets.toml` the same way
  Cloud does): secrets.toml -> bridge -> env -> get_secret -> live services
  -> findings rendered. (Hit one transient `RemoteDisconnected` on a Search
  call mid-test; retried clean -- network blip, not a code issue.)

**Version control finally done** (open since Phase P0): `git init` on
`main`, first commit `b75e93e`, 43 files. `.gitignore` extended to exclude
`.streamlit/secrets.toml` (real keys), `reports/`, and `.claude/`/`.agents/`
(local Claude tooling/skills -- were staged as symlink/gitlink entries,
correctly excluded). `.streamlit/config.toml` (the theme) IS committed.

**`.streamlit/secrets.toml` generated** (gitignored) holding the 7 real
service secret values, read from Key Vault -- for pasting into the
Streamlit Cloud secrets UI. Values were never printed to the transcript.

**Remaining steps are user-side (cannot be automated from here):**
`gh` CLI isn't installed and Streamlit Cloud deploy is a web UI, so:
1. Create a GitHub repo (private is fine -- Community Cloud supports it),
   then `git remote add origin <url>` + `git push -u origin main` (the push
   triggers Git Credential Manager's browser login).
2. On share.streamlit.io: sign in with GitHub, pick the repo, set main file
   = `app.py`, paste the contents of `.streamlit/secrets.toml` into
   Settings -> Secrets, deploy.

**Cost/security note carried forward**: user chose PUBLIC / no-login. That
leaves OpenAI + (now paid S0) Doc Intelligence quota open to anyone with the
URL. The budget-alert to-do (open since P1) is the real backstop and still
needs doing -- but it must be set in the ACTIVE subscription that holds the
paid services (the "DEFAULT DIRECTORY" tenant), not the dead Students one.

### DEPLOYED LIVE + login gate + two post-deploy baseline bug fixes (2026-07-19)

**The app is now live**: https://contract-review-pilot.streamlit.app ,
deployed from GitHub repo `sayan9404/contract-review-pilot` (branch `main`,
main file `app.py`). The user did the two user-side steps from the hosting
section below (create GitHub repo + `git push`, then deploy on
share.streamlit.io pasting `.streamlit/secrets.toml` into the Cloud Secrets
box). Streamlit Cloud auto-redeploys on every push to `main`.

**Login gate added** (`app.py::_require_login`): user asked for a
username/password gate before deploy. Single shared credential, read from
`APP_USERNAME`/`APP_PASSWORD` secrets (NOT hardcoded -- so the password
stays out of the public GitHub repo; added to the gitignored
`.streamlit/secrets.toml` and pasted into Cloud Secrets alongside the 7
Azure keys). Constant-time compare via `hmac.compare_digest`; gate runs
right after `set_page_config` and `st.stop()`s everything until authed;
sign-out button clears the session. Current credentials: `admin` /
`admin@9404`. Verified end-to-end via AppTest (blocks -> rejects wrong pw
-> admits correct -> sign-out returns to gate). This is a "keep strangers
out" gate, NOT real user management -- the budget alert (still open) is the
real backstop for the public/no-login-quota exposure.

**Azure error surfacing** (`app.py`): Streamlit Cloud redacts uncaught
exceptions, so a failed baseline write showed only a generic
`HttpResponseError` with no detail. The three write dialogs
(disable/enable/promote) now catch `HttpResponseError` and `st.error` the
real HTTP status + message, so Azure failures are legible in-app instead of
a redacted crash.

**Bug 1 (reported as "disable throws HttpResponseError on Cloud")**: turned
out to self-resolve -- verified the `SEARCH_KEY` in secrets IS the admin
key (matches Key Vault exactly) and reproduced the exact disable write
(read 43 active chunks, write them back) from a local machine: it
succeeded. Key/SDK/data all fine; the earlier transient error didn't recur.
Error surfacing (above) shipped anyway so any future Azure error is visible.

**Bug 2 (reported as "Add to baseline confirms, but sidebar still shows no
active baseline") -- REAL, two-part bug, fixed**:
- Root cause in the data: promoting the SAME `document_id` twice (promote ->
  disable -> promote again) left one `(document_id, version)` with MIXED
  statuses -- 27 active chunks + 16 stale superseded ones. Because the
  chunking had changed between the two promotes, the old chunks had
  different `chunk_id`s and weren't overwritten, so they lingered as
  orphans under the same version.
- Display bug (`ingest/index.py::list_all_documents`): it collapsed each
  `(document_id, version)` to one row via `setdefault`, reporting whichever
  chunk it happened to read first. With mixed statuses it read a superseded
  one first and labeled the whole doc "superseded" -> sidebar's active-only
  filter hid it -> "No active baseline documents yet", even though 27 chunks
  were genuinely active and in use by retrieval. **Fix**: a
  `(document_id, version)` now reads as `active` if ANY of its chunks is
  active (matches what the `status eq 'active'` retrieval filter actually
  uses). Verified against the live index: the Azure agreement now correctly
  returns active.
- Prevention (`ingest/promote.py`): the "new document" path always used
  `version=1` and never cleaned up, which is what allowed the orphan mix. It
  now checks `list_all_documents()` for prior history on that `document_id`
  and, if found, bumps to `max(existing version)+1` and supersedes the prior
  active set -- so chunk IDs never collide across promote generations again.
- **Known residual data state (not code)**: the existing `(azure_..., v1)`
  still has those 16 orphan superseded chunks mixed in. Harmless now
  (excluded from retrieval; sidebar reads correctly). The only way they'd
  resurface is a manual Enable of that old v1. Offered to delete just those
  16 orphan chunks to make the version perfectly clean -- pending user's
  yes/no. Cleanest long-term recovery is a re-promote (now goes to a clean
  v2 thanks to the prevention fix above).

Commits this session (on top of the initial `b75e93e`): login gate, HANDOFF
update, error surfacing, and the baseline display+promote fix; plus a
`5385d49 Added Dev Container Folder` commit the user added via GitHub
(rebased on cleanly).

### Residual-risk hardening + honest multi-run verification (2026-07-17)

Friend made two good points on the chunking fix above: (1) the token-budget-fit
merge only removes the near-empty competitor when table+text fits the
budget -- for a table too large to merge, the forced split could still
orphan a near-empty heading chunk beside it, same bug class on a bigger
document; and (2) a single clean run is weak evidence for a nondeterminism
fix, since the old code also passed 2 runs out of 3 -- the real test is
repeated runs landing identically.

**Residual hardening (ingest/chunk.py)**: the forced-split branch now folds
the pre-table buffer into the table's chunk not only when they fit together,
but also whenever the buffer is smaller than one overlap-carry window
(`max_tokens * overlap_pct / 100`, = 128 tok at default config). That
boundary is the system's own definition of "context-sized, not a standalone
chunk," so it's not a fresh magic number. Only a buffer that is BOTH
substantial (>= that boundary) AND over budget is split off on its own --
which is real prose, never a degenerate near-empty competitor. Verified
three cases: real Roles section still -> 1 chunk; synthetic heading +
2400-token oversized table -> 1 chunk (heading folded in, no orphan, the
exact residual case); synthetic 200-token prose + oversized table -> 2
chunks (substantial prose correctly stays standalone, no over-merging).

**Multi-run verification -- the friend was right to insist, and it split the
result cleanly**: built an isolated test (no index) feeding the Roles clause
+ the correct merged baseline passage into `assess_clause` 6 times at
temperature=0. Result:
- **Gap verdict: STABLE. gap=False and risk=Low on all 6 runs.** This is
  the actual correctness bug (the run-3 false-positive flip) and it's now
  fixed and proven: the flip was entirely driven by which chunk got
  retrieved (noise fragment -> "gap" vs real table -> "no gap"), and with
  the chunking fix guaranteeing one coherent chunk, the verdict no longer
  moves. This directly resolves the friend's PRIMARY concern.
- **Category label: STILL UNSTABLE. "Resource obligations" vs "Governance"
  across the 6 runs, even at temperature=0.** So temperature=0 was
  necessary but NOT sufficient for category stability. Not papering over
  this: the cause is inherent LLM serving nondeterminism at a decision
  boundary (this clause genuinely straddles two defensible categories), not
  a retrieval artifact -- temperature=0 tightens the distribution but can't
  make an exact-tie argmax deterministic across GPU-batched serving.

**Why this still matters (don't under-rate it):** category instability isn't
purely cosmetic, because the category decides WHICH coverage-matrix row a
clause lands in. Same clause -> different row between runs -> the coverage
matrix itself isn't row-level reproducible, even though each row's gap flag
is now correct. That's the friend's audit-trail point, and it's valid.

**The real fix for category stability is a design decision, deliberately
NOT made unprompted** (the friend ranked it lower priority, and it's real
work): the robust option is deterministic category assignment -- e.g. a
keyword/section-heading -> category rules layer with LLM fallback only for
genuinely ambiguous clauses, matching the same "deterministic layer"
philosophy already used for critical terms. A cheaper partial mitigation is
prompt-level tie-break guidance (e.g. "when a clause fits multiple
categories, prefer the earliest-listed applicable one"), which reduces but
won't eliminate boundary flipping. Left for the user to choose between.

**Still required to activate on live data**: the re-promote from the prior
section. The gap-stability result above was proven against the FIXED
chunking of the file on disk; the user's live index still holds the old
fragmented chunks until they re-promote the baseline (Add to baseline ->
revision of itself). Until then, a live run can still exhibit the old flip.

### Real bug found by user's friend: coverage matrix conflated "flagged for review" with "genuine gap" (2026-07-17)

User's friend re-reviewed the app after the clause-extraction fix and found
the coverage matrix's `gap` column was `True` for categories where every
individual clause's own narrative said "no gap" / "no action required" --
specifically caught it on `Governance` (2 clauses, both explicitly no-gap,
bucket still `True`) and predicted (correctly) that `Security & compliance`
would show the same pattern once its hidden second clause was visible.

**Root cause, confirmed by reading the code, not by trusting the report**:
`analysis/report.py::build_coverage_matrix()` computed
`gap_categories = {finding.category for finding in findings}` and used
category membership in that set as the coverage matrix's `gap` flag. But
`findings` includes clauses that became a `Finding` because the
deterministic rules layer force-flagged them (by design -- a critical-term
clause always reaches human review, regardless of what the LLM itself
concluded) even when `assessment.gap == False`. So any category with a
force-flagged-but-not-actually-a-gap clause got marked `gap=True` at the
whole-category level, even when zero clauses in it were genuine gaps.

**Fix**: `gap` is now `any(a.gap for a in clause_assessments)` -- the raw
LLM gap judgment per clause, independent of whether a Finding exists for
procedural (force-flag) reasons. Also split the `review` text into three
distinct states instead of two: "flagged as gap", "rules-flagged for
review, no confirmed gap", and "no gap flagged" -- the middle case is new,
and exactly closes the audit-trail gap the friend flagged (a category
showing a Finding with no confirmed gap needs to read differently from one
with neither).

**Verified against the real 9-page contract**: `Governance` and
`Security & compliance` (the friend's flagged case plus their correctly
predicted third instance) and `Resource obligations` all now correctly
show `gap=False` with the new "rules-flagged for review, no confirmed gap"
text. `SLA response & resolution` and `Commercial / legal clauses` (which
do have genuine LLM-confirmed gaps) correctly remain `gap=True`. Also
regression-checked against `analysis/generate.py` -- unchanged, `build_findings`
untouched, so the actual Findings list (F001, F002, ...) a reviewer sees is
identical to before; only the coverage-matrix rollup changed.

**Second thing the friend flagged, lower priority but real**: category
assignment (which of the 18 fixed categories a clause gets classified into)
wasn't stable across identical re-runs of the same document -- same clause,
different category label each time. Added `temperature=0` to
`analysis/generate.py::assess_clause`'s chat completion call (confirmed
this model/endpoint accepts the parameter before adding it -- it rejected
`max_tokens` earlier this project in favor of `max_completion_tokens`, so
nothing about this API surface gets assumed anymore). Reduces but doesn't
eliminate run-to-run variance; most LLM serving stacks aren't perfectly
deterministic even at temperature=0.

**A "regression check" ran into an unrelated, real gotcha worth recording**:
re-ran `contract_B_clean_renewal.md` (originally validated at zero findings
in Phase P3) and got 3 findings, which looked like a regression at first.
It wasn't -- traced it to `analysis/retrieve.py` correctly filtering to
`status=active`, and the *only* active baseline document right now is the
user's own real Azure contract (the 4 synthetic docs are still disabled
from earlier testing). So contract_B's clauses were being compared against
the wrong baseline entirely, coincidentally, not because of anything
touched today. Confirmed via a direct `retrieve()` call showing only
`Azure_Enterprise_Cloud_Modernization_Agreement.pdf` results. **Any
analysis run right now, on any contract, only ever compares against the
real Azure contract** until the synthetic docs are re-enabled (sidebar ->
"Show disabled versions too" -> Enable) -- deliberately not doing that
without being asked, consistent with every other baseline-state decision
this session.

### UI visual polish pass (2026-07-17)

User asked to make the UI "more professional and attractive," no specific
style given. Used the `developing-with-streamlit` skill's `design.md` and
`theme.md` references (skill invocation itself failed to resolve this
turn -- read the reference files directly from
`.claude/skills/developing-with-streamlit/` instead, same content).

Chose the **Fluent** theme template (Microsoft blue `#0078D4`, Segoe UI) --
this tool reviews Azure-centric enterprise contracts, so it's a deliberate
on-brand choice, not arbitrary. New `.streamlit/config.toml`.

Changes to `app.py`, all sourced from the skill's stated best practices
rather than personal taste:
- Emoji risk badges (🔴🟠🟡⚖️) -> inline colored badges
  (`:red-badge[High]` etc.) via markdown badge syntax.
- `st.radio(..., horizontal=True)` for reviewer decisions -> `st.segmented_control`
  (skill explicitly flags horizontal radio as an anti-pattern this replaces).
  Also simplified: dropped the unclickable "-- pending --" pseudo-option --
  `segmented_control` with `required=False` already returns to `None`
  (pending) when you click the selected option again, no dummy option needed.
- The promotion dialog's "new document vs. revision" radio -> `st.segmented_control`
  (2 options, single-select, all-visible -- the exact case the skill names).
- "Show disabled versions too" `st.checkbox` -> `st.toggle` (it's an
  app-level display setting, not a form field -- skill's stated rule for
  when to use which).
- Material Symbols icons added throughout (buttons, headers, tabs, dialogs,
  alerts) in place of emoji/bare text.
- Coverage matrix `st.dataframe` got `column_config` for human-readable
  column headers instead of raw dict keys (`contract_area` -> "Contract area").
- Removed `st.divider()` calls in the sidebar per the skill's spacing
  guidance ("dividers look heavy... default spacing is usually enough").

**Compatibility gotcha found and fixed while verifying**: the installed
Streamlit version (1.59.2) does **not** have an `icon=` parameter on
`st.title`/`st.header`/`st.subheader` (confirmed via `inspect.signature`,
not assumed from the skill doc, which describes a newer API surface) --
would have been a real `TypeError` if shipped as initially written. Fixed
by embedding the `:material/icon_name:` directive directly in the text
instead of passing a separate `icon=` kwarg, which this version does
support on those elements.

**Verified via `AppTest`**: clean startup, sample-contract selection, run
analysis, all 4 segmented controls render with the right options, findings
render with the new badge syntax, sidebar toggle works, coverage-matrix
dataframe renders under the correct tab with all 5 columns. Confirmed the
user's live baseline data (5 real documents) was untouched throughout --
this pass only touched `app.py` and added `.streamlit/config.toml`, no
backend/index code changed.

### PDF and DOCX upload support added (2026-07-15)

User wanted to upload real PDF/Word files, not just `.md`. Turned out
simpler than expected: DI's prebuilt-layout model natively accepts PDF and
DOCX (`application/pdf`, `.../wordprocessingml.document`) with zero
conversion, unlike Markdown which needs the HTML-conversion workaround
(see P2 above). Changes:

- `ingest/parse.py` refactored -- pulled the "turn a DI `AnalyzeResult` into
  a `ParsedDocument`" logic (table-cell dedup, reading-order interleave,
  heading tracking) out of `parse_markdown_file` into a shared
  `_to_parsed_document()`, so the new `parse_office_file()` (PDF/DOCX) reuses
  it instead of duplicating it. Also fixed page numbers to be read from each
  element's real `bounding_regions` instead of being hardcoded `None` --
  didn't matter when everything was single-page Markdown, matters now.
- `parse_baseline_file()` renamed to **`parse_document_file()`** (it was
  already misnamed before this -- `analysis/run_analysis.py` was calling
  `parse_markdown_file` directly, bypassing the dispatcher entirely, so
  contracts could only ever be `.md`). All three call sites
  (`ingest/run_ingest.py`, `analysis/run_analysis.py`, `eval/run_eval.py`)
  now go through the one dispatcher.
- `app.py`'s uploader now accepts `.md`, `.pdf`, `.docx`.

**Verified, not assumed**: generated real throwaway test fixtures (a `.docx`
via `python-docx` and a `.pdf` via `reportlab`, both mirroring contract A's
planted-gap content, then uninstalled both packages afterward -- they're
test-fixture tools only, not app dependencies). Confirmed:
1. `parse_office_file()` on each directly -- correct headings/paragraphs
   extracted, DI returned real page numbers for the PDF (`page: 1`) but
   `None` for the DOCX -- expected, DOCX has no fixed pagination at the API
   level, not a bug.
2. Full `analysis/run_analysis.py` pipeline on each -- both produced the
   identical, correct 4 findings (same as the `.md` version).
3. The actual Streamlit upload widget, using `AppTest`'s `FileUploader.upload()`
   (not just the underlying function) -- uploaded the test PDF through
   `app.py`'s real sidebar `file_uploader`, clicked "Run analysis", confirmed
   F001-F004 rendered. This is the same widget path a real user's click
   would take.

## All phases (P0-P4) are now built and passing their checkpoints

What's left is optional polish, not a required next phase:
- Fix the two known cosmetic gaps noted in the P1 section above (exact
  Doc Intelligence resource tier, double-checking names in the Portal).
- `git init` + first commit -- still not done, see below. This is now the
  single biggest risk in the whole project: months of work across P0-P4
  exist only on this laptop's disk.
- If ever exercising this beyond synthetic data: everything in
  `analysis/generate.py`'s prompt already treats clause/passage text as
  untrusted data, not instructions (see P3 section above) -- that safeguard
  was built in from the start, not bolted on later.

## Reminders that matter

- **Synthetic data only.** Never place real Metso/Inomotics/Primark documents
  in this repo or the Azure resources above.
- **Cost hygiene**: only upgrade AI Search to Basic tier temporarily when
  actually testing semantic ranking in P3; downgrade/delete afterward. Set a
  budget alert in Azure Cost Management if you haven't already.
- Skip `.venv/` when zipping/transferring — reinstall via
  `pip install -r requirements.txt` on the new machine instead.
