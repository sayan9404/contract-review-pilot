# Contract Review — Personal Pilot Build

A personal, learning-scale implementation of the AI-Assisted Contract Review &
Gap Analysis pipeline described in the Proposal / Architecture / Technical
Foundation docs. Built solo on an Azure for Students subscription.

**Resuming on a new machine or a new session?** Read [`HANDOFF.md`](HANDOFF.md)
first — it has the exact state of what's been provisioned, what's left, and
known gotchas. The full implementation plan is in
[`docs/implementation_plan.md`](docs/implementation_plan.md).

**Data policy: synthetic only.** Everything under `data/` is fictional,
generated for pipeline testing. Never place real client (e.g. Metso,
Inomotics, Primark) documents in this repo or in the Azure resources it
talks to.

## Phases (mirrors the Architecture doc's P0-P4)

| Phase | What it does | Entry point |
|---|---|---|
| P0 | Local scaffolding, config, synthetic data, schemas | (this phase — no code to run) |
| P1 | Provision Azure resources (Portal, manual) | `scripts/check_connections.py` |
| P2 | Ingest baseline docs -> chunk -> embed -> index | `ingest/run_ingest.py` |
| P3 | Analyze one new contract -> gap report | `analysis/run_analysis.py` |
| P4 | Evaluate against the labelled test set | `eval/run_eval.py` |
| UI | Local Streamlit app: upload/pick a contract, review findings, ask questions | `streamlit run app.py` |

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# edit .env: set AZURE_KEY_VAULT_URL once Key Vault is provisioned (Phase P1)
```

## Repo layout

```
config/       locked pipeline parameters (categories, critical terms, chunking)
data/         synthetic baseline docs + synthetic contracts + labelled test set
shared/       Pydantic schemas + Azure client/auth setup
ingest/       baseline ingestion pipeline (parse -> chunk -> embed -> index)
analysis/     per-contract analysis pipeline (rules -> retrieve -> generate -> report -> chat)
eval/         metrics + scorecard against the labelled test set, + review CLI
app.py        Streamlit UI over the pipeline above (local only)
```

## Cost hygiene (Azure for Students)

- Azure AI Search: keep on **Free** tier by default; only upgrade to **Basic**
  while actively testing semantic ranking, then downgrade/delete.
- Set a budget alert in Azure Cost Management early.
- Private endpoints and Entra RBAC role-separation are intentionally skipped
  in this personal build (see Architecture doc §2.5 for what production
  restores).
