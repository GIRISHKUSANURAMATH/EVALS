"""Vectorisation backends.

TF-IDF (scikit-learn) is the default and always available. sentence-transformers is
optional: it is only imported when explicitly enabled, and any failure (package not
installed, model not downloadable offline) falls back to TF-IDF.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[str, Any] = {}


def tfidf_vectors(texts: list[str], analyzer: str = "char_wb") -> Any:
    if analyzer == "char_wb":
        # use_idf=False keeps pairwise similarity independent of the rest of the upload:
        # two strings get the same score whether they arrive in a file of 10 or 10,000 records.
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True, use_idf=False)
    else:
        vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, stop_words="english", sublinear_tf=True)
    return vec.fit_transform(texts)


def embedding_backend_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("sentence_transformers") is not None
    except Exception:  # pragma: no cover - defensive
        return False


def semantic_vectors(texts: list[str], use_embeddings: bool, model_name: str) -> tuple[Any, str]:
    """Return (matrix, backend_name). Rows are L2-normalised."""
    if use_embeddings and embedding_backend_available():
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

            model = _MODEL_CACHE.get(model_name)
            if model is None:
                model = SentenceTransformer(model_name)
                _MODEL_CACHE[model_name] = model
            emb = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
            return np.asarray(emb), f"sentence-transformers:{model_name}"
        except Exception as exc:  # network / model errors -> graceful fallback
            logger.warning("Embedding model unavailable (%s); falling back to TF-IDF.", type(exc).__name__)
    return tfidf_vectors(texts), "tfidf-char"
