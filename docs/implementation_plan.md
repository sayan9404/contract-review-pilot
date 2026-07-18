# Implementation Plan: AI-Assisted Contract Review & Gap Analysis (Personal Build)

> Copied into the repo from the Claude Code plan file so it survives a
> machine change. Approved as-is (no edits) on 2026-07-10. See `../HANDOFF.md`
> for what's actually been done so far against this plan.

## Context

The three planning documents (Proposal v1.2, Architecture & Delivery Plan,
Technical Foundation) define *what* to build and *why*. Nothing has been
implemented yet — the working directory only contains the finalized proposal
docx. The user wants to start hands-on implementation now, on a personal
Azure for Students subscription, using synthetic contract/SOW data only
(confirmed — no real client data in this environment).

Goal of this plan: stand up a working end-to-end pilot (ingestion pipeline ->
analysis pipeline -> gap report) that mirrors the architecture doc's P0-P4
phases, scoped so it's buildable and testable solo on a student subscription,
before any of it touches real accounts.

**Decisions locked in for this build:**
- **Language**: Python — best Azure SDK/RAG library support.
- **Provisioning**: Manual via Azure Portal (no Bicep/Terraform for this
  personal build).
- **Ingestion**: Hand-rolled pipeline (own code for parse -> chunk -> embed ->
  index), not Search's integrated vectorization — matches the tech doc's
  emphasis on structure-aware, table-aware chunking that generic indexers
  don't give you.
- **Storage**: real Azure Storage Account from day one, no local emulator
  (Azurite). Reasoning: emulation only ever applies to Blob Storage — Document
  Intelligence, AI Search semantic ranking, and Azure OpenAI have no local
  emulator and must be called against real endpoints regardless, so an
  emulator wouldn't change accuracy at all, and skipping it removes a moving
  part while matching production behavior exactly. Storage cost at this scale
  is negligible.

## Repo Structure

```
contract-review/
  .env.example              # names of required secrets/endpoints, no real values
  .gitignore                # .env, data/synthetic_* stays IN repo (it's fake), __pycache__, etc.
  requirements.txt
  README.md
  HANDOFF.md                 # progress log / handoff notes (added during build)
  docs/
    implementation_plan.md    # this file
  config/
    categories.json         # MVP category set (Scope of services, Support hours, SLA, ... from tech doc §7)
    critical_terms.json     # critical-terms list (24x7, P1/P2, RTO/RPO, GDPR, ... from tech doc §11)
    chunking.json           # {"max_tokens":512, "overlap_pct":25, "respect_sentence_boundaries":true}
  data/
    synthetic_baseline/     # fake SOW, SLA matrix, policy doc, skills matrix (source of truth)
    synthetic_contracts/    # 2-3 fake "new contracts" with deliberately planted gaps
    labelled_test_set.json  # answer key: which findings are true gaps, for eval
  shared/
    azure_clients.py        # client/auth setup for Storage, Doc Intelligence, Search, OpenAI
    schemas.py               # Pydantic models: Finding, CoverageRow, ClauseInventoryEntry
  ingest/
    parse.py                # Document Intelligence Layout model -> structured text
    chunk.py                 # structure-aware chunking using config/chunking.json
    embed.py                 # text-embedding-3-large calls
    index.py                 # AI Search index create/push
    run_ingest.py             # orchestrates baseline: parse -> chunk -> embed -> index
  analysis/
    parse_contract.py         # parse new contract into clause inventory
    rules.py                  # deterministic critical-term regex scan
    retrieve.py                # hybrid + semantic query against baseline index
    generate.py                 # prompt build + chat model call, enforced JSON schema output
    report.py                   # assemble findings + coverage matrix + citations
    run_analysis.py               # orchestrates one contract end-to-end
  eval/
    metrics.py                    # clause extraction %, citation accuracy, critical miss rate, FP rate, recall@K
    run_eval.py                    # runs analysis over labelled_test_set.json, prints scorecard
  scripts/
    check_connections.py           # P1 checkpoint smoke test (added during build)
```

## Phase P0 — Foundation (local only, no Azure cost) — DONE, see HANDOFF.md

1. `git init` in `contract-review/`, add `.gitignore`, `requirements.txt`
   (azure-ai-documentintelligence, azure-search-documents, openai,
   azure-identity, azure-storage-blob, azure-keyvault-secrets, pydantic,
   tiktoken, python-dotenv, pandas).
2. Write `config/categories.json` and `config/critical_terms.json` directly
   from Technical Foundation §7 and §11 (already enumerated in the doc —
   copy verbatim, don't re-derive).
3. Write `config/chunking.json` with the locked defaults (512 tokens, 25%
   overlap, sentence-boundary aware).
4. Create synthetic data:
   - `data/synthetic_baseline/`: a short fake SOW (with a "support hours"
     clause, e.g. "L2 support during business hours"), a fake SLA matrix
     (P1/P2 response targets), one policy doc, one skills matrix.
   - `data/synthetic_contracts/`: 2-3 fake new contracts. At least one should
     replicate the doc's own running scenario style (e.g. a clause requiring
     "24x7 support, 15-min P1 response" not covered by the fake baseline) so
     there's a guaranteed true-positive gap to detect from day one.
   - `data/labelled_test_set.json`: for each synthetic contract, the known
     true gaps/no-gaps, so `eval/run_eval.py` has ground truth immediately
     (this doubles as the P4 test set — build it now, not later).
5. Define `shared/schemas.py`: a `Finding` Pydantic model matching the exact
   JSON schema in Technical Foundation §8 (finding_id, category, risk_level,
   contract_reference, baseline_reference, reason, confidence,
   recommended_action, reviewer_decision).

**Checkpoint**: everything above runs with zero Azure resources provisioned —
pure local scaffolding and fake data.

## Phase P1 — Provision (Azure Portal, manual) — IN PROGRESS, see HANDOFF.md

Order matters — do the highest-risk/uncertain item first:

1. **Azure OpenAI access check (do this FIRST — biggest risk item)**: in the
   portal, try to create an Azure OpenAI resource on the student
   subscription. If it's blocked/not offered, stop and report back before
   doing anything else in this phase — the whole Generation and Embedding
   layers depend on it. If it works, deploy two models:
   `text-embedding-3-large` and a current GPT chat model deployment.
2. Resource Group: one RG for the whole pilot (e.g. `rg-contractreview-pilot`).
3. Storage Account (Standard, LRS is fine): create 4 containers —
   `pilot-baseline`, `pilot-incoming`, `pilot-processed`, `pilot-reports`
   (single "pilot" client prefix is enough since there's no real multi-client
   isolation need yet — the container-per-client *pattern* is what matters to
   demonstrate, not real client names).
4. Azure AI Document Intelligence: create on **F0 (free)** tier first — 500
   pages/month is enough for synthetic data.
5. Azure AI Search: create on **Free** tier first for basic hybrid retrieval.
   Note for later: semantic ranking requires **Basic** tier minimum — don't
   upgrade until Phase P3 when you actually test semantic reranking, then
   downgrade/delete afterward to conserve credit.
6. Key Vault: store every connection string/key here (Storage conn string,
   Doc Intelligence key+endpoint, Search key+endpoint, OpenAI key+endpoint).
   Local code reads from Key Vault via `azure-identity`
   (`DefaultAzureCredential`, using your own `az login` session) — never
   hardcode keys in `.env` committed to git; `.env` holds only the Key Vault
   URL.
7. Skip private endpoints and Entra RBAC role-separation for this personal
   build (both require paid SKUs / are moot for a single-user learning
   project) — note in README that production would restore both per
   Architecture doc §2.5.

**Checkpoint**: `shared/azure_clients.py` can successfully fetch each secret
from Key Vault and instantiate all 4 service clients (Blob, Document
Intelligence, Search, OpenAI). Write a tiny `scripts/check_connections.py`
smoke test for this.

## Phase P2 — Ingestion Pipeline (build & validate baseline path) — NOT STARTED

1. `ingest/parse.py`: call Document Intelligence Layout model on each file in
   `data/synthetic_baseline/`; return text + structure (tables, headings,
   page/section numbers).
2. `ingest/chunk.py`: structure-aware chunking per `config/chunking.json` —
   split on section/heading boundaries first, then token-window with overlap
   inside long sections; never split a table mid-row; attach metadata
   (section, page, heading, source doc name) to every chunk.
3. `ingest/embed.py`: batch-embed chunks with `text-embedding-3-large`.
4. `ingest/index.py`: create the Azure AI Search index (vector field + text
   fields + metadata fields + semantic config), push embedded chunks.
5. `ingest/run_ingest.py`: wires parse -> chunk -> embed -> index over the
   whole `synthetic_baseline/` folder.
6. **Validate parse quality** (this is the architecture doc's M2 gate): print
   a mini clause-inventory summary (page count, detected sections/clauses,
   tables found) per doc and eyeball it against the actual fake SOW content —
   confirm nothing got silently dropped.

## Phase P3 — Analysis Pipeline (build the review engine) — NOT STARTED

1. `analysis/parse_contract.py`: same Document Intelligence Layout call,
   applied to one synthetic "new contract," producing its own clause
   inventory.
2. `analysis/rules.py`: regex/keyword scan of every clause against
   `config/critical_terms.json`; force-flag matches independent of anything
   downstream.
3. `analysis/retrieve.py`: for each new clause, run hybrid (keyword+vector)
   query against the baseline index from P2, then semantic rerank (requires
   temporarily upgrading Search to Basic tier — see P1 note).
4. `analysis/generate.py`: build the grounded prompt (new clause + retrieved
   baseline passages only, explicit "no baseline found -> say so"
   instruction), call the chat model with enforced JSON schema output
   matching `shared/schemas.py::Finding`.
5. `analysis/report.py`: assemble all findings + a coverage matrix (per
   `config/categories.json`) + citations into one JSON report (and optionally
   a simple Markdown render for readability). Enforce the "no citation, no
   accepted finding" rule here in code — findings missing a valid baseline or
   contract reference get downgraded to `"unverified"` rather than shown as
   accepted.
6. `analysis/run_analysis.py`: orchestrates steps 1-5 for one contract
   end-to-end.

**Checkpoint** (architecture doc's M3 gate): run `run_analysis.py` against
the synthetic contract with the planted 24x7/P1 gap and confirm the report
correctly flags it as HIGH risk with both citations and a rules-layer
force-flag.

## Phase P4 — Evaluate — NOT STARTED

1. `eval/metrics.py`: implement the 4 measurable metrics from Technical
   Foundation §13 that apply at this scale — clause extraction quality,
   citation accuracy, critical miss rate (must be zero against your planted
   gaps), false positive rate — plus retrieval Recall@K.
2. `eval/run_eval.py`: runs `run_analysis.py` over every contract in
   `data/synthetic_contracts/`, compares findings against
   `data/labelled_test_set.json`, prints a scorecard against the MVP
   exit-gate targets table (Proposal §09 / Architecture §1.3).
3. Minimal human-review step: since a full review UI is out of scope for a
   solo learning build, a simple CLI/notebook step that lists flagged
   findings and lets you mark `accept/reject/escalate` (writing back into the
   report JSON's `reviewer_decision` field) is enough to demonstrate the
   exception-based review loop end-to-end.

## Cost & Housekeeping

- After each working session: downgrade/delete the AI Search Basic-tier
  instance if you upgraded it for semantic-rank testing; Document
  Intelligence F0 and Storage cost is negligible either way.
- Set a budget alert in Azure Cost Management early (e.g. at $20/$50/$80 of
  the $100 credit) so nothing surprises you.
- Never place real client (Metso/Inomotics/Primark) documents anywhere in
  this environment — synthetic data only, per the user's own confirmation.

## Verification

- P0 verified by running each script locally with no Azure resources
  touched — synthetic files exist and parse as valid JSON/Pydantic objects.
- P1 verified by `scripts/check_connections.py` succeeding against all 4
  provisioned services.
- P2 verified by inspecting the clause-inventory summary and confirming the
  AI Search index is populated (query it directly for a known baseline
  phrase).
- P3 verified by the end-to-end run on the planted-gap contract producing
  the expected HIGH-risk, cited, rules-flagged finding.
- P4 verified by the eval scorecard hitting (or explaining misses against)
  the MVP exit-gate targets table.
