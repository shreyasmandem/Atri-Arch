"""CPU text embeddings with a zero-download fallback.

Preference order:

1. **fastembed** with BAAI/bge-small-en-v1.5 - a real 384-dimensional sentence
   embedding running on ONNX Runtime. CPU-only, ~130 MB, no GPU, no API, no cost.
2. **Hashed character n-gram projection** - a deterministic sparse-to-dense
   embedding computed in pure NumPy with no model at all.

The fallback is not a toy. Character n-gram hashing captures morphological and
lexical similarity well, which is most of what matters for a domain corpus full
of material names and technical terms, and it degrades gracefully rather than
failing. Combined with the BM25 half of the hybrid index, retrieval stays useful
even on a machine that has never downloaded a model - which is what keeps the
"runs anywhere, costs nothing" promise true for the whole pipeline and not just
the parts that are convenient.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from typing import Sequence

import numpy as np

from aip.core.config import get_settings
from aip.core.logging import get_logger, log_event

logger = get_logger("aip.rag.embed")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder:
    """Text to dense vector."""

    def __init__(self, dimension: int, backend: str) -> None:
        self.dimension = dimension
        self.backend = backend

    @property
    def is_neural(self) -> bool:
        return self.backend == "fastembed"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        raise NotImplementedError

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


class FastEmbedEmbedder(Embedder):
    """Real sentence embeddings via ONNX Runtime on CPU."""

    def __init__(self, model_name: str, dimension: int) -> None:
        super().__init__(dimension, "fastembed")
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)
        self._lock = threading.Lock()

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        with self._lock:
            vectors = list(self._model.embed(list(texts)))
        matrix = np.asarray(vectors, dtype=np.float32)
        return _l2_normalise(matrix)


class HashingEmbedder(Embedder):
    """Deterministic character n-gram hashing projection.

    Each document is decomposed into word tokens and character 3/4-grams, hashed
    into a fixed number of buckets with a signed hash, weighted sub-linearly by
    frequency, and L2 normalised. The result behaves like a compressed TF-IDF
    vector: cosine similarity between two vectors tracks lexical and
    morphological overlap closely enough to be genuinely useful for retrieval,
    and it needs no model, no download and no network.
    """

    def __init__(self, dimension: int = 384) -> None:
        super().__init__(dimension, "hashing")

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for feature, weight in self._features(text).items():
                index, sign = self._bucket(feature)
                matrix[row, index] += sign * weight
        return _l2_normalise(matrix)

    def _features(self, text: str) -> dict[str, float]:
        tokens = _TOKEN_RE.findall(text.lower())
        counts: dict[str, float] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0.0) + 1.0
            # Character n-grams give robustness to inflection and compounds
            # ("waterproofing" / "waterproof"), which matters in a technical corpus.
            padded = f"^{token}$"
            for size in (3, 4):
                for i in range(len(padded) - size + 1):
                    gram = padded[i : i + size]
                    counts[gram] = counts.get(gram, 0.0) + 0.4
        # Sub-linear scaling stops long documents from dominating.
        return {feature: 1.0 + math.log(count) for feature, count in counts.items()}

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dimension, 1.0 if (value >> 63) & 1 else -1.0


def _l2_normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms < 1e-9] = 1.0
    return matrix / norms


_embedder: Embedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> Embedder:
    """Process-wide embedder, chosen once at first use."""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _embedder_lock:
        if _embedder is not None:
            return _embedder
        settings = get_settings()
        try:
            _embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim)
            log_event(logger, "embedder.ready", backend="fastembed", model=settings.embedding_model)
        except Exception as exc:  # noqa: BLE001 - the fallback is the design
            log_event(
                logger, "embedder.fallback", level=30,
                reason=f"{type(exc).__name__}: {exc}",
                detail="Using hashing embedder; install the 'embeddings' extra for neural retrieval.",
            )
            _embedder = HashingEmbedder(settings.embedding_dim)
        return _embedder


def reset_embedder() -> None:
    """Test hook."""
    global _embedder
    _embedder = None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise cosine similarity between a query vector and a matrix."""
    if b.size == 0:
        return np.zeros(0, dtype=np.float32)
    return b @ a
