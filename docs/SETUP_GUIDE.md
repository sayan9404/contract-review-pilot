# Setup Guide — AI-Assisted Contract Review & Gap Analysis

A step-by-step runbook to set up and run this application **from zero**. It
assumes no prior context on the project — an L1 engineer should be able to
follow it top to bottom and end with either a working local app or a live
hosted one.

> **Golden rule: synthetic data only.** Never upload real client contracts
> to this pilot (local or hosted). All test data in `data/` is synthetic.

---

## 1. What this application does

You give it a contract (Markdown, PDF, or Word). It:
1. **Parses** the document into clauses (Azure Document Intelligence).
2. **Retrieves** the most relevant passages from a **baseline** knowledge
   base of reference/approved contract language (Azure AI Search, hybrid +
   semantic search).
3. **Analyzes** each clause against the baseline with an LLM (Azure OpenAI)
   plus a deterministic critical-terms rules layer, producing **findings**
   (gaps/risks with citations) and a **coverage matrix**.
4. Lets a reviewer **accept/reject/escalate** findings, **ask questions**
   about the report, and **promote** documents into the baseline (with
   versioning: revise, disable, re-enable).

The UI is a **Streamlit** app (`app.py`). The pipeline is plain Python under
`ingest/` (baseline side) and `analysis/` (contract side).

---

## 2. Architecture at a glance

```
                 ┌─────────────────────────────────────────────┐
   Contract ──►  │  app.py (Streamlit UI, login-gated)         │
   (md/pdf/docx) └───────────────┬─────────────────────────────┘
                                 │
             ┌───────────────────┴───────────────────┐
             ▼                                        ▼
   analysis/run_analysis.py                 ingest/ (baseline build)
   parse → rules → retrieve → generate      parse → chunk → embed → index
   → report                                 → promote (version/status)
             │                                        │
             ▼                                        ▼
   ┌───────────────────────── Azure services ──────────────────────────┐
   │ Document Intelligence  │ AI Search (index) │ Azure OpenAI (Foundry)│
   │ (prebuilt-layout, S0)  │ hybrid+semantic   │ chat + embeddings     │
   └────────────────────────┴───────────────────┴───────────────────────┘
        secrets fetched from Azure Key Vault (local) OR env vars (hosted)
```

**Secrets model (important):** the app reads each secret from an environment
variable first, and only falls back to **Azure Key Vault** if the env var is
unset (see `shared/azure_clients.py::get_secret`).
- **Local dev** sets no env vars → uses Key Vault via your `az login`.
- **Hosted (Streamlit Cloud)** provides secrets via `st.secrets`, which
  `app.py` bridges into env vars → no Key Vault / `az login` needed.

---

## 3. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| **Python** | **3.10–3.12** | Avoid 3.14 (see Troubleshooting). 3.11 recommended. |
| **Git** | any recent | For version control + hosting. |
| **Azure subscription** | any that isn't spending-limit locked | See note below. |
| **Azure CLI** (`az`) | 2.80+ | For `az login` (local dev only). |
| **GitHub account** | — | Only if hosting on Streamlit Cloud. |

> **Azure subscription caveat:** "Azure for Students" subscriptions get
> spending-limit locked when credit runs out and become **read-only**
> (writes fail with `ReadOnlyDisabledSubscription`). If provisioning fails
> that way, you need a different active subscription. The **data services**
> (Key Vault, Search, OpenAI, Document Intelligence) can live in any active
> subscription — the app only ever talks to them via their keys over HTTPS.

---

## 4. Provision Azure resources

Do this once. Create everything in **one resource group**, in a **single
region** that supports the models you need.

> **Region constraint (learned the hard way):** `text-embedding-3-large` is
> not deployable in every region. **`southeastasia` works** for both the
> embedding and chat models. Some subscriptions (e.g. Azure for Students)
> are policy-restricted to a small region list — check **Subscription →
> Policy → Compliance** if a region is rejected. Keep every resource in the
> same region.

Provision these (Portal is fine; names are examples — pick your own):

| # | Resource | Example name | Tier / config |
|---|---|---|---|
| 1 | Resource Group | `rg-contractreview-pilot` | your chosen region |
| 2 | **Azure AI Foundry** project (Azure OpenAI) | `contractreview-pilot` | with 2 deployments ↓ |
| 2a | — chat model deployment | `gpt-5.4` | Global Standard |
| 2b | — embedding model deployment | `text-embedding-3-large` | Global Standard (3072-dim) |
| 3 | **Document Intelligence** | `docintel-contractreview-pilot` | **S0** (NOT F0 — see below) |
| 4 | **Azure AI Search** | `search-contractreview-pilot` | Free tier is fine |
| 5 | **Storage Account** | `stcontractreviewpilot` | Standard LRS (optional for core flow) |
| 6 | **Key Vault** | `kv-contractreview-pilot` | RBAC access model |

> **Document Intelligence MUST be S0, not F0.** The Free (F0) tier
> **silently caps analysis at 2 pages per document** — no error, it just
> returns the first 2 pages. This corrupts multi-page contracts. Layout on
> S0 costs ~$1.50/1,000 pages (negligible at pilot scale). The app has a
> `TruncatedAnalysisError` guard that fails loudly if a document comes back
> truncated, but the real fix is provisioning S0.

**Deployment names must match** the constants in
`shared/azure_clients.py`:
```python
EMBEDDING_DEPLOYMENT = "text-embedding-3-large"
CHAT_DEPLOYMENT = "gpt-5.4"
```
If you name your deployments differently, update those two constants.

---

## 5. Collect the 7 secret values

From the Portal, gather these (you'll store them in Key Vault and/or paste
into hosting secrets). **Never commit these anywhere.**

| Secret name (Key Vault) | Where to find it |
|---|---|
| `storage-connection-string` | Storage account → Access keys → Connection string |
| `docintel-endpoint` | Document Intelligence → Keys and Endpoint → Endpoint |
| `docintel-key` | Document Intelligence → Keys and Endpoint → KEY 1 |
| `search-endpoint` | AI Search → Overview → Url |
| `search-key` | AI Search → Settings → Keys → **Primary admin key** (needs write access) |
| `openai-endpoint` | Foundry **project** endpoint (`.../api/projects/<name>`) |
| `openai-key` | Foundry project → API key |

> **`search-key` must be the ADMIN key, not a query key.** The app writes to
> the index (promoting/disabling baseline docs), which a read-only query key
> can't do.

> **`openai-endpoint` is the Foundry *project* endpoint**
> (`https://<res>.services.ai.azure.com/api/projects/<name>`). The app
> derives the v1 inference URL (`.../openai/v1/`) from it — do **not** use
> the classic Azure OpenAI endpoint + api-version, that combination fails
> with "API version not supported".

---

## 6. Store secrets in Key Vault (for local dev)

1. In Key Vault, create 7 secrets with the **exact names** in the table above.
2. **Grant yourself data-plane access.** Key Vault uses **Azure RBAC**, and
   being subscription *Owner* is NOT enough (that's control-plane only). Add
   an IAM role assignment on the vault:
   - Role: **Key Vault Secrets Officer** (read+write) or **Key Vault Secrets
     User** (read-only, enough to run the app).
   - Assign to: your own account.
   - Scope: the vault.

If secret reads fail locally with a 403/Forbidden, this role assignment is
almost always the cause.

---

## 7. Local setup

```bash
# 1. Clone (or copy) the repo, then cd into it
cd contract-review

# 2. Create a fresh virtual environment with a supported Python
python -m venv .venv           # use python3.11 if available
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Point .env at your Key Vault
cp .env.example .env           # (copy manually on Windows)
# edit .env and set:
#   AZURE_KEY_VAULT_URL=https://<your-vault-name>.vault.azure.net/

# 5. Log in so DefaultAzureCredential can read Key Vault
az login
```

> **If you copied `.venv` from another machine, delete it and recreate it.**
> A copied venv keeps a hardcoded path to the old machine's Python and every
> command fails with "did not find executable". Always recreate locally.

**Verify connectivity** before anything else:
```bash
python scripts/check_connections.py
```
Expect 4 `[OK]` lines (Key Vault+Storage, Document Intelligence, AI Search,
Azure OpenAI). Fix any failure here before proceeding — it isolates
credential/permission problems from app logic.

---

## 8. Build the baseline index

The app needs a baseline to compare contracts against. Seed it with the
synthetic baseline docs:

```bash
python ingest/run_ingest.py
```

This parses every file in `data/synthetic_baseline/`, chunks + embeds them,
creates the AI Search index (`contractreview-baseline`), and pushes them as
active baseline documents (version 1). It's idempotent — safe to re-run.

You can also manage the baseline entirely from the UI later ("Add to
baseline" on any analyzed contract, plus disable/enable per version).

---

## 9. Run the app locally

```bash
streamlit run app.py
```

Open the local URL it prints. You'll hit the **login screen** first (see
§11 for credentials). Then:
- Sidebar → pick a sample contract or upload your own (`.md`/`.pdf`/`.docx`)
  → **Run analysis**.
- Tabs: **Findings & review**, **Coverage matrix**, **Ask about this report**.
- Sidebar → **Current baseline**: promote/disable/enable baseline docs.

> **Don't edit `app.py` while `streamlit run` is live.** Editing the file
> underneath a running server has caused stale-state glitches. Stop the
> server, edit, then restart.

---

## 10. Deploy to Streamlit Community Cloud (free hosting)

The app is fully portable (talks to Azure over HTTPS with keys), so it hosts
off-Azure with no changes.

### 10a. Push to GitHub
1. Create an **empty** repo at github.com/new (private is fine — Community
   Cloud supports private repos). Do **not** add a README/.gitignore/license
   (the push must be to an empty repo).
2. From the repo root:
   ```bash
   git remote add origin https://github.com/<user>/<repo>.git
   git push -u origin main
   ```
   The first push opens a browser login (Git Credential Manager). After it
   completes, confirm on GitHub that **`.streamlit/secrets.toml` is NOT
   listed** — it's gitignored and must never be pushed.

### 10b. Deploy
1. Go to [share.streamlit.io](https://share.streamlit.io) → sign in with
   GitHub → **Create app** → deploy from your repo.
2. Set: Repository = your repo, Branch = `main`, Main file path = `app.py`.
3. **Advanced settings:**
   - **Python version: 3.11 or 3.12** (do NOT use 3.14 — see Troubleshooting).
   - **Secrets:** paste the entire contents of your local
     `.streamlit/secrets.toml` (the 7 Azure keys **plus** the two
     `APP_USERNAME`/`APP_PASSWORD` login lines — see §11).
4. **Deploy.** First build takes a few minutes.

After it's live, **every `git push` to `main` auto-redeploys.** Secrets are
managed in the Cloud UI (**Manage app → Settings → Secrets**), not in git.

### The `.streamlit/secrets.toml` format
This file is **gitignored**. Create it locally with your real values:
```toml
STORAGE_CONNECTION_STRING = "..."
DOCINTEL_ENDPOINT = "https://....cognitiveservices.azure.com/"
DOCINTEL_KEY = "..."
SEARCH_ENDPOINT = "https://....search.windows.net"
SEARCH_KEY = "..."
OPENAI_ENDPOINT = "https://....services.ai.azure.com/api/projects/<name>"
OPENAI_KEY = "..."

# App login gate (not an Azure secret)
APP_USERNAME = "admin"
APP_PASSWORD = "admin@9404"
```
> The env-var **key names are the Key Vault secret names, upper-snake-cased**
> (`storage-connection-string` → `STORAGE_CONNECTION_STRING`). The app's
> `get_secret` does this mapping automatically.

---

## 11. Login

The whole app is gated behind a single username/password (`app.py::_require_login`).

- **Default credentials:** username `admin`, password `admin@9404`.
- Credentials come from the `APP_USERNAME` / `APP_PASSWORD` secrets — **not**
  hardcoded, so they stay out of the public repo.
- **To change them:** edit those two lines in local `.streamlit/secrets.toml`
  **and** in the Cloud **Manage app → Settings → Secrets** box.
- If you see "Login is not configured", the two secrets are missing from
  wherever the app is running.

> This is a "keep strangers out" gate, not real user management. If the app
> is public, **set an Azure budget alert** (Cost Management, on the
> subscription holding the paid Doc Intelligence/OpenAI) so an open URL can't
> silently run up quota.

---

## 12. Troubleshooting (every real gotcha hit in this project)

| Symptom | Cause | Fix |
|---|---|---|
| `HttpResponseError` on baseline write, redacted on Cloud | Streamlit Cloud hides uncaught exceptions | App now `st.error`s the real message; also check **Manage app → logs** for the full trace |
| Multi-page PDF returns only ~2 pages of clauses | Document Intelligence **F0** tier 2-page cap | Upgrade the resource to **S0** |
| "API version not supported" from OpenAI | Using classic `AzureOpenAI` + api-version against a **Foundry project** endpoint | Already handled — endpoint must be the `.../api/projects/<name>` form; app derives `.../openai/v1/` |
| Chat call rejects `max_tokens` | `gpt-5.4` requires `max_completion_tokens` | Already handled in `analysis/generate.py` |
| Key Vault secret read → 403 | RBAC role missing (Owner ≠ data access) | Grant **Key Vault Secrets User/Officer** on the vault |
| "did not find executable" running any script | `.venv` copied from another machine | Delete `.venv`, recreate with local Python |
| `text-embedding-3-large` won't deploy | Region doesn't support it | Use `southeastasia` (or another supported region); keep all resources co-located |
| Baseline write fails with 403 specifically | `search-key` is a **query** (read-only) key | Use the **primary admin** key |
| Sidebar shows "No active baseline" after a successful promote | (Fixed) mixed-status chunks under one version + display collapse | Already fixed in `list_all_documents` + `promote.py`; re-promote for a clean version |
| `az webapp create` → `ReadOnlyDisabledSubscription` | Subscription is spending-limit locked | Use an active subscription; or host off-Azure (Streamlit Cloud) |
| Azure SDK errors only on Streamlit Cloud, not locally | Cloud defaulted to **Python 3.14** (bleeding-edge) | Pin **Python 3.11/3.12** in the app's Advanced settings |
| Transient `RemoteDisconnected` on a Search call | Network blip | Retry; not a code issue |

---

## 13. Repository map

| Path | What it is |
|---|---|
| `app.py` | Streamlit UI (login gate, upload, analysis tabs, baseline management) |
| `shared/azure_clients.py` | All Azure client builders + `get_secret` (env-var-first, KV fallback) |
| `shared/schemas.py` | Pydantic models (Finding, CoverageRow, BaselineChunk, GapReport, …) |
| `ingest/` | Baseline build: `parse` → `chunk` → `embed` → `index`, plus `promote` (versioning) and `run_ingest` (seed script) |
| `analysis/` | Contract analysis: `parse_contract`, `rules`, `retrieve`, `generate`, `report`, `run_analysis`, `chat` |
| `eval/` | Evaluation harness (`metrics`, `run_eval`, `review`) — scores against `data/labelled_test_set.json` |
| `config/` | `categories.json`, `critical_terms.json`, `chunking.json` |
| `data/synthetic_baseline/`, `data/synthetic_contracts/` | Synthetic test data (safe to use) |
| `scripts/check_connections.py` | Connectivity smoke test — run first |
| `.streamlit/config.toml` | Theme (committed) |
| `.streamlit/secrets.toml` | Real secrets — **gitignored, never commit** |
| `.env` | Local Key Vault URL only — gitignored |
| `HANDOFF.md` | Full chronological build/decision log |
| `docs/implementation_plan.md` | Original phased plan (P0–P4) |

---

## 14. Quick-start checklist

- [ ] Azure: resource group + Foundry (2 deployments) + Doc Intelligence **S0** + AI Search + Key Vault, all in a supported region
- [ ] 7 secrets in Key Vault; **Key Vault Secrets User** role granted to you
- [ ] `.env` → `AZURE_KEY_VAULT_URL`; `az login` done
- [ ] `python -m venv .venv` (local Python 3.11) + `pip install -r requirements.txt`
- [ ] `python scripts/check_connections.py` → 4× `[OK]`
- [ ] `python ingest/run_ingest.py` → baseline seeded
- [ ] `streamlit run app.py` → log in with `admin` / `admin@9404`
- [ ] (Hosting) push to GitHub → deploy on share.streamlit.io, Python 3.11, paste `secrets.toml`
- [ ] Set an Azure **budget alert** if the app is public
