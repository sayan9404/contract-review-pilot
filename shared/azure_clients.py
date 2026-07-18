"""Central place to build every Azure client the pipeline needs.

Auth model: every real secret (Storage connection string, Document
Intelligence key/endpoint, AI Search key/endpoint, Azure OpenAI key/endpoint)
lives in Key Vault, not in .env or code. Locally, DefaultAzureCredential picks
up your own `az login` session to read Key Vault; no keys are hardcoded here.

Only the Key Vault URL itself is a local setting (.env: AZURE_KEY_VAULT_URL).
"""
from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Secret names as stored in Key Vault -- create them with these exact names
# when you provision each resource in Phase P1.
SECRET_STORAGE_CONN_STRING = "storage-connection-string"
SECRET_DOCINTEL_ENDPOINT = "docintel-endpoint"
SECRET_DOCINTEL_KEY = "docintel-key"
SECRET_SEARCH_ENDPOINT = "search-endpoint"
SECRET_SEARCH_KEY = "search-key"
SECRET_OPENAI_ENDPOINT = "openai-endpoint"
SECRET_OPENAI_KEY = "openai-key"

# Deployment names as they exist in the Foundry project (confirmed against
# the live resource -- see HANDOFF.md P2 section for how these were verified).
EMBEDDING_DEPLOYMENT = "text-embedding-3-large"
CHAT_DEPLOYMENT = "gpt-5.4"


@lru_cache(maxsize=1)
def _kv_client() -> SecretClient:
    vault_url = os.environ["AZURE_KEY_VAULT_URL"]
    return SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())


def _env_name(secret_name: str) -> str:
    """Kebab-case Key Vault secret name -> UPPER_SNAKE env var name, e.g.
    'storage-connection-string' -> 'STORAGE_CONNECTION_STRING'."""
    return secret_name.replace("-", "_").upper()


@lru_cache(maxsize=None)
def get_secret(name: str) -> str:
    """Read a secret, preferring an environment variable over Key Vault.

    Hosted deployments (App Service, containers) provide the secret values
    directly as env vars / app settings, so the running app needs no Key
    Vault access and no `az login` / managed identity -- see HANDOFF.md's
    hosting section. Local dev sets none of these env vars, so it falls
    through to Key Vault via DefaultAzureCredential exactly as before.
    """
    env_value = os.environ.get(_env_name(name))
    if env_value:
        return env_value
    return _kv_client().get_secret(name).value


def get_blob_service_client() -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(get_secret(SECRET_STORAGE_CONN_STRING))


def get_document_intelligence_client() -> DocumentIntelligenceClient:
    return DocumentIntelligenceClient(
        endpoint=get_secret(SECRET_DOCINTEL_ENDPOINT),
        credential=AzureKeyCredential(get_secret(SECRET_DOCINTEL_KEY)),
    )


def get_search_index_client() -> SearchIndexClient:
    return SearchIndexClient(
        endpoint=get_secret(SECRET_SEARCH_ENDPOINT),
        credential=AzureKeyCredential(get_secret(SECRET_SEARCH_KEY)),
    )


def get_search_client(index_name: str) -> SearchClient:
    return SearchClient(
        endpoint=get_secret(SECRET_SEARCH_ENDPOINT),
        index_name=index_name,
        credential=AzureKeyCredential(get_secret(SECRET_SEARCH_KEY)),
    )


def get_openai_client() -> OpenAI:
    """Client for the Azure AI Foundry project's OpenAI-compatible v1 API.

    The secret stored in Key Vault is the *project* endpoint
    (".../api/projects/<name>"), but the v1 inference API lives at the
    resource root (".../openai/v1/") -- the classic `AzureOpenAI` client and
    its api-version query param don't work against a Foundry project
    endpoint, hence building an `OpenAI` client with a derived base_url
    instead.
    """
    parsed = urlparse(get_secret(SECRET_OPENAI_ENDPOINT))
    base_url = f"{parsed.scheme}://{parsed.netloc}/openai/v1/"
    return OpenAI(base_url=base_url, api_key=get_secret(SECRET_OPENAI_KEY))
