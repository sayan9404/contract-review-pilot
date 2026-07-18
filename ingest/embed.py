"""Phase P2 step 3: batch-embed chunks with the text-embedding-3-large
deployment."""
from __future__ import annotations

from shared import azure_clients as az
from shared.schemas import BaselineChunk

_BATCH_SIZE = 16


def embed_chunks(chunks: list[BaselineChunk]) -> list[BaselineChunk]:
    if not chunks:
        return chunks
    client = az.get_openai_client()
    for start in range(0, len(chunks), _BATCH_SIZE):
        batch = chunks[start : start + _BATCH_SIZE]
        response = client.embeddings.create(
            model=az.EMBEDDING_DEPLOYMENT,
            input=[chunk.text for chunk in batch],
        )
        for chunk, item in zip(batch, response.data):
            chunk.embedding = item.embedding
    return chunks
