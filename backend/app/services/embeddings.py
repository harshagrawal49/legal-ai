"""Text embeddings, computed locally with fastembed (small ONNX model, no API key needed).

To switch to a hosted legal embedding model later (e.g. Voyage), change these two functions and
`embedding_dim` in config, then re-run ingestion.
"""

from functools import lru_cache

from fastembed import TextEmbedding

from app.config import get_settings

# bge models expect this prefix on queries (not on documents) for retrieval.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache
def _model() -> TextEmbedding:
    return TextEmbedding(get_settings().embedding_model)


def embed_documents(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _model().embed(texts, batch_size=32)]


def embed_query(text: str) -> list[float]:
    return next(iter(_model().embed([QUERY_PREFIX + text]))).tolist()
