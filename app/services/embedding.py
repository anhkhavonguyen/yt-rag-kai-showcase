# Copyright 2024
# Directory: yt-rag/app/services/embedding.py

"""
Embedding service for generating text embeddings using OpenAI.
Focused solely on vector embeddings for RAG retrieval.
"""

import logging
import math
from typing import List, Sequence
import openai
from ..core.config import DEFAULT_OPENAI_BASE_URL, get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def fit_dimensions(vector: Sequence[float], dimensions: int) -> List[float]:
    """Return `vector` with exactly `dimensions` values.

    Longer vectors are truncated and rescaled to unit length. Gemini and OpenAI
    `text-embedding-3` models are trained so that a leading prefix is itself a
    valid lower-dimensional embedding. Shorter vectors can't be fixed and raise.
    """
    size = len(vector)
    if size == dimensions:
        return list(vector)
    if size < dimensions:
        raise ValueError(
            f"Embedding model returned {size} values but EMBEDDING_DIMENSIONS is {dimensions}; "
            "use a model that returns at least that many, or lower EMBEDDING_DIMENSIONS "
            "and the VECTOR size in sql/init_supabase.sql together."
        )
    prefix = list(vector[:dimensions])
    norm = math.sqrt(sum(x * x for x in prefix))
    return [x / norm for x in prefix] if norm else prefix


class EmbeddingService:
    """Service for generating text embeddings using OpenAI."""
    
    def __init__(self):
        """Initialize the OpenAI-compatible client for embeddings."""
        self.openai_client = openai.OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or DEFAULT_OPENAI_BASE_URL,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        self.embed_model = settings.openai_embed_model
    
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        
        Args:
            texts: List of text strings to embed
            
        Texts are sent in batches of at most EMBEDDING_BATCH_SIZE, and every
        returned vector has exactly EMBEDDING_DIMENSIONS values.

        Returns:
            One embedding per input text, in input order
        """
        dimensions = settings.embedding_dimensions
        batch_size = settings.embedding_batch_size
        embeddings: List[List[float]] = []

        try:
            for start in range(0, len(texts), batch_size):
                batch = texts[start:start + batch_size]
                request = {"model": self.embed_model, "input": batch}
                if settings.embedding_send_dimensions:
                    request["dimensions"] = dimensions

                response = self.openai_client.embeddings.create(**request)

                items = list(response.data)
                if len(items) != len(batch):
                    raise ValueError(
                        f"Embedding provider returned {len(items)} embeddings for {len(batch)} texts"
                    )
                # Keep input order even if the provider reorders its results.
                if all(isinstance(getattr(item, "index", None), int) for item in items):
                    items.sort(key=lambda item: item.index)

                embeddings.extend(fit_dimensions(item.embedding, dimensions) for item in items)

            logger.info(f"Generated embeddings for {len(texts)} texts")
            return embeddings

        except Exception as e:
            logger.error(f"Failed to generate embeddings: {type(e).__name__}: {e}")
            raise
    
    async def embed_query(self, query: str) -> List[float]:
        """
        Generate embedding for a single query.
        
        Args:
            query: Query text to embed
            
        Returns:
            Embedding vector
        """
        embeddings = await self.embed_texts([query])
        return embeddings[0]


# Global service instance
embedding_service = EmbeddingService()
