"""Retrieval-augmented generation and continual learning.

Two jobs:

* **Grounding.** Style guidance, material properties, climatic strategy and
  precedent are retrieved from a curated corpus and injected into agent context,
  so recommendations cite something rather than being invented.

* **Learning.** Every completed project, architect override and client decision
  is fed back, which is what makes the platform improve for a specific practice
  rather than staying at the industry average.
"""

from aip.rag.embeddings import Embedder, get_embedder
from aip.rag.retriever import retrieve, retrieve_for_brief
from aip.rag.store import Document, HybridIndex, get_index

__all__ = [
    "Document",
    "Embedder",
    "HybridIndex",
    "get_embedder",
    "get_index",
    "retrieve",
    "retrieve_for_brief",
]
