"""Phase P1 checkpoint: confirm every provisioned Azure service is reachable
before writing any pipeline logic against it.

Run after: (1) provisioning Storage, Document Intelligence, AI Search,
Azure OpenAI, and Key Vault in the portal, (2) storing their keys/endpoints
in Key Vault under the names in shared/azure_clients.py, and (3) `az login`
with an identity that has "Key Vault Secrets User" on the vault.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from shared import azure_clients as az  # noqa: E402


def check(label: str, fn) -> bool:
    try:
        fn()
        print(f"[OK]   {label}")
        return True
    except Exception as exc:  # noqa: BLE001 -- smoke test, we want to see everything
        print(f"[FAIL] {label}: {exc}")
        return False


def main() -> None:
    results = []

    def check_storage():
        client = az.get_blob_service_client()
        list(client.list_containers(results_per_page=1))

    def check_docintel():
        az.get_document_intelligence_client()

    def check_search():
        client = az.get_search_index_client()
        list(client.list_index_names())

    def check_openai():
        client = az.get_openai_client()
        client.embeddings.create(model=az.EMBEDDING_DEPLOYMENT, input="connection check")

    results.append(check("Key Vault + Storage connection string", check_storage))
    results.append(check("Document Intelligence client", check_docintel))
    results.append(check("AI Search client", check_search))
    results.append(check("Azure OpenAI client", check_openai))

    print()
    if all(results):
        print("All services reachable. Ready for Phase P2 (ingestion).")
    else:
        print("One or more services failed -- fix before starting Phase P2.")
        sys.exit(1)


if __name__ == "__main__":
    main()
