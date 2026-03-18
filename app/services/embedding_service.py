"""OpenAI embedding service for vector generation."""

from typing import List, Optional
import openai
from openai import AsyncOpenAI
import structlog

from app.config import settings

logger = structlog.get_logger()

EMBEDDING_DIMENSIONS = 1536

_sync_client: Optional[openai.OpenAI] = None
_async_client: Optional[AsyncOpenAI] = None


def _get_sync_client() -> openai.OpenAI:
    global _sync_client
    if _sync_client is None:
        _sync_client = openai.OpenAI(api_key=settings.openai_api_key)
    return _sync_client


def _get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _async_client


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Batch-embed a list of texts (synchronous, for Celery workers).

    Handles OpenAI's per-request limit by splitting into batches of 2048.
    """
    client = _get_sync_client()
    all_embeddings: List[List[float]] = []
    batch_size = 2048

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=batch,
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    logger.info(
        "Generated embeddings",
        total_texts=len(texts),
        model=settings.openai_embedding_model,
    )
    return all_embeddings


def embed_query(text: str) -> List[float]:
    """Embed a single query text (synchronous)."""
    client = _get_sync_client()
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
    )
    return response.data[0].embedding


async def aembed_query(text: str) -> List[float]:
    """Embed a single query text (async, for FastAPI request handlers)."""
    client = _get_async_client()
    response = await client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
    )
    return response.data[0].embedding
