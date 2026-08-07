"""Hybrid retrieval index.

Combines BM25 lexical scoring with dense vector similarity via reciprocal rank
fusion. The two retrieve differently and fail differently: BM25 nails exact
technical terms ("M25 concrete", "chajja", "Nairutya") that an embedding blurs,
while the dense side handles paraphrase and intent. Fusing ranks rather than
scores avoids having to calibrate two incomparable scales.

Persistence is a single JSON file plus a NumPy array. That is deliberate - a
vector database is another service to run, another thing to pay for, and at the
corpus size a single architecture practice generates it buys nothing.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from aip.core.config import get_settings
from aip.core.logging import get_logger, log_event
from aip.rag.embeddings import get_embedder

logger = get_logger("aip.rag.store")


@dataclass(slots=True)
class Document:
    """One retrievable passage."""

    id: str
    text: str
    source: str = ""
    kind: str = "reference"          # reference | style | material | precedent | feedback
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Learned quality signal. Raised when a passage informs an accepted design.
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "text": self.text, "source": self.source, "kind": self.kind,
            "tags": self.tags, "metadata": self.metadata, "weight": self.weight,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        return cls(
            id=data["id"], text=data["text"], source=data.get("source", ""),
            kind=data.get("kind", "reference"), tags=data.get("tags", []),
            metadata=data.get("metadata", {}), weight=float(data.get("weight", 1.0)),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass(slots=True)
class SearchHit:
    document: Document
    score: float
    lexical_rank: int | None = None
    dense_rank: int | None = None


class HybridIndex:
    """BM25 + dense retrieval with reciprocal rank fusion."""

    #: RRF damping. 60 is the value from the original Cormack et al. work and is
    #: robust across corpus sizes; it stops any single ranker from dominating.
    RRF_K = 60

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or (settings.cache_dir / "rag_index")
        self.path.mkdir(parents=True, exist_ok=True)
        self.documents: list[Document] = []
        self._vectors: np.ndarray | None = None
        self._bm25 = None
        self._lock = threading.Lock()
        self._dirty = False

    # ------------------------------------------------------------ mutation --

    def add(self, documents: Iterable[Document], *, rebuild: bool = True) -> int:
        """Add documents, ignoring ids already present."""
        existing = {d.id for d in self.documents}
        added = 0
        with self._lock:
            for doc in documents:
                if doc.id in existing:
                    continue
                self.documents.append(doc)
                existing.add(doc.id)
                added += 1
            if added:
                self._dirty = True
        if added and rebuild:
            self.rebuild()
        return added

    def upsert(self, document: Document) -> None:
        with self._lock:
            for index, existing in enumerate(self.documents):
                if existing.id == document.id:
                    self.documents[index] = document
                    self._dirty = True
                    return
            self.documents.append(document)
            self._dirty = True

    def boost(self, document_id: str, delta: float) -> bool:
        """Adjust a document's learned weight after a design outcome."""
        with self._lock:
            for doc in self.documents:
                if doc.id == document_id:
                    doc.weight = max(0.15, min(4.0, doc.weight + delta))
                    self._dirty = True
                    return True
        return False

    def rebuild(self) -> None:
        """Recompute embeddings and the BM25 index."""
        if not self.documents:
            self._vectors = None
            self._bm25 = None
            return

        started = time.perf_counter()
        embedder = get_embedder()
        texts = [self._indexable(d) for d in self.documents]
        self._vectors = embedder.encode(texts)

        try:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi([t.lower().split() for t in texts])
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "bm25.unavailable", level=30, error=str(exc))
            self._bm25 = None

        log_event(
            logger, "index.rebuilt",
            documents=len(self.documents), backend=embedder.backend,
            ms=round((time.perf_counter() - started) * 1000, 1),
        )

    @staticmethod
    def _indexable(document: Document) -> str:
        parts = [document.text]
        if document.tags:
            parts.append(" ".join(document.tags))
        if document.source:
            parts.append(document.source)
        return " ".join(parts)

    # ------------------------------------------------------------- search --

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        kinds: set[str] | None = None,
        tags: set[str] | None = None,
    ) -> list[SearchHit]:
        """Retrieve the most relevant passages, fusing both rankers."""
        if not self.documents:
            return []
        if self._vectors is None:
            self.rebuild()

        candidates = [
            index for index, doc in enumerate(self.documents)
            if (kinds is None or doc.kind in kinds)
            and (tags is None or (tags & set(doc.tags)))
        ]
        if not candidates:
            return []

        dense_ranks = self._dense_ranks(query, candidates)
        lexical_ranks = self._lexical_ranks(query, candidates)

        fused: dict[int, float] = {}
        for index in candidates:
            score = 0.0
            if index in dense_ranks:
                score += 1.0 / (self.RRF_K + dense_ranks[index])
            if index in lexical_ranks:
                score += 1.0 / (self.RRF_K + lexical_ranks[index])
            # The learned weight nudges passages that have proven useful before.
            fused[index] = score * self.documents[index].weight

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [
            SearchHit(
                document=self.documents[index],
                score=round(score, 6),
                dense_rank=dense_ranks.get(index),
                lexical_rank=lexical_ranks.get(index),
            )
            for index, score in ordered
        ]

    def _dense_ranks(self, query: str, candidates: list[int]) -> dict[int, int]:
        if self._vectors is None:
            return {}
        vector = get_embedder().encode_one(query)
        subset = self._vectors[candidates]
        similarities = subset @ vector
        order = np.argsort(-similarities)
        return {candidates[int(pos)]: rank + 1 for rank, pos in enumerate(order)}

    def _lexical_ranks(self, query: str, candidates: list[int]) -> dict[int, int]:
        if self._bm25 is None:
            return {}
        scores = self._bm25.get_scores(query.lower().split())
        pairs = [(index, scores[index]) for index in candidates if index < len(scores)]
        pairs.sort(key=lambda kv: kv[1], reverse=True)
        return {index: rank + 1 for rank, (index, _score) in enumerate(pairs)}

    # -------------------------------------------------------- persistence --

    def save(self) -> None:
        with self._lock:
            payload = {
                "version": 1,
                "documents": [d.to_dict() for d in self.documents],
            }
            (self.path / "documents.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            if self._vectors is not None:
                np.save(self.path / "vectors.npy", self._vectors)
            self._dirty = False
        log_event(logger, "index.saved", documents=len(self.documents), path=str(self.path))

    def load(self) -> bool:
        doc_path = self.path / "documents.json"
        if not doc_path.exists():
            return False
        try:
            payload = json.loads(doc_path.read_text(encoding="utf-8"))
            self.documents = [Document.from_dict(d) for d in payload.get("documents", [])]
        except (json.JSONDecodeError, KeyError) as exc:
            log_event(logger, "index.load_failed", level=30, error=str(exc))
            return False

        vector_path = self.path / "vectors.npy"
        if vector_path.exists():
            try:
                vectors = np.load(vector_path)
                # A stale cache from a different embedder must not be trusted.
                if vectors.shape[0] == len(self.documents):
                    self._vectors = vectors
                else:
                    self.rebuild()
            except Exception:  # noqa: BLE001
                self.rebuild()
        else:
            self.rebuild()

        if self._bm25 is None and self.documents:
            self.rebuild()
        log_event(logger, "index.loaded", documents=len(self.documents))
        return True

    @property
    def size(self) -> int:
        return len(self.documents)

    def stats(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for doc in self.documents:
            kinds[doc.kind] = kinds.get(doc.kind, 0) + 1
        return {
            "documents": len(self.documents),
            "by_kind": kinds,
            "embedder": get_embedder().backend,
            "lexical_index": self._bm25 is not None,
            "path": str(self.path),
        }


_index: HybridIndex | None = None
_index_lock = threading.Lock()


def get_index() -> HybridIndex:
    """Process-wide index, seeded from the built-in corpus on first use."""
    global _index
    if _index is not None:
        return _index
    with _index_lock:
        if _index is not None:
            return _index
        index = HybridIndex()
        if not index.load():
            from aip.rag.corpus import seed_documents

            index.add(seed_documents(), rebuild=True)
            try:
                index.save()
            except Exception as exc:  # noqa: BLE001 - a read-only FS is survivable
                log_event(logger, "index.save_failed", level=30, error=str(exc))
        _index = index
        return _index


def reset_index() -> None:
    """Test hook."""
    global _index
    _index = None
