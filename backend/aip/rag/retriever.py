"""Retrieval entry points and the continual-learning feedback loop."""

from __future__ import annotations

import asyncio
from typing import Any

from aip.agents.base import Evidence, EvidenceKind
from aip.core.logging import get_logger, log_event
from aip.domain.brief import ClientBrief
from aip.rag.store import Document, SearchHit, get_index

logger = get_logger("aip.rag.retrieve")


async def retrieve(
    query: str,
    *,
    top_k: int = 8,
    kinds: set[str] | None = None,
    tags: set[str] | None = None,
) -> list[Evidence]:
    """Search the corpus and return citable evidence."""
    index = get_index()
    hits = await asyncio.to_thread(index.search, query, top_k=top_k, kinds=kinds, tags=tags)
    return [_to_evidence(hit) for hit in hits]


async def retrieve_for_brief(brief: ClientBrief, top_k: int | None = None) -> list[Evidence]:
    """Assemble grounding for a brief from several targeted queries.

    A single concatenated query retrieves poorly here, because a brief mixes
    unrelated intents - aesthetic, climatic, typological - and averaging them
    into one vector lands between all of them. Issuing separate queries per
    facet and merging the results retrieves passages that are each strongly
    relevant to something, rather than weakly relevant to everything.
    """
    from aip.core.config import get_settings

    settings = get_settings()
    limit = top_k or settings.retrieval_top_k

    queries: list[tuple[str, set[str] | None]] = []

    styles = " ".join(s.label for s in brief.style.styles)
    if styles:
        queries.append((f"{styles} design style palette materials finishes", {"style"}))

    if brief.style.materials_liked:
        queries.append((" ".join(brief.style.materials_liked) + " material properties", {"material"}))

    climate = _climate_terms(brief)
    queries.append((f"{climate} passive design ventilation daylight shading", {"reference"}))

    room_terms = " ".join(
        r.type.label for r in sorted(brief.requirements, key=lambda r: -r.priority)[:5]
    )
    if room_terms:
        queries.append((f"{room_terms} planning ergonomics dimensions", {"reference"}))

    typology = f"{brief.kind.value} {brief.site.plot_area:.0f} sqm plot"
    if brief.occupants:
        typology += " " + " ".join(o.role for o in brief.occupants)
    queries.append((typology, {"precedent"}))

    if brief.free_text:
        queries.append((brief.free_text, None))

    index = get_index()
    per_query = max(2, limit // max(1, len(queries)) + 1)

    results = await asyncio.gather(
        *(
            asyncio.to_thread(index.search, text, top_k=per_query, kinds=kinds)
            for text, kinds in queries
        )
    )

    merged: dict[str, SearchHit] = {}
    for hits in results:
        for hit in hits:
            existing = merged.get(hit.document.id)
            if existing is None or hit.score > existing.score:
                merged[hit.document.id] = hit

    ordered = sorted(merged.values(), key=lambda h: h.score, reverse=True)[: limit * 2]
    log_event(
        logger, "retrieve.brief",
        queries=len(queries), unique_hits=len(merged), returned=len(ordered),
    )
    return [_to_evidence(hit) for hit in ordered]


def _climate_terms(brief: ClientBrief) -> str:
    """Coarse climate classification from latitude, used to steer retrieval."""
    lat = abs(brief.site.latitude)
    locality = (brief.site.locality or "").lower()
    coastal = any(
        term in locality
        for term in ("chennai", "mumbai", "kochi", "goa", "kolkata", "vizag", "mangalore", "coastal")
    )
    if lat < 15:
        return "hot humid tropical coastal" if coastal else "hot humid tropical"
    if lat < 25:
        return "hot humid composite coastal" if coastal else "warm humid composite"
    if lat < 32:
        return "composite hot dry"
    return "cold temperate"


def _to_evidence(hit: SearchHit) -> Evidence:
    doc = hit.document
    # Fusion scores are small by construction; map to a readable 0-1 relevance.
    relevance = min(1.0, hit.score * 45.0)
    return Evidence(
        kind=EvidenceKind.CORPUS,
        source=doc.source or "corpus",
        detail=doc.text[:600],
        value=round(hit.score, 6),
        relevance=round(relevance, 3),
        locator=doc.id,
    )


# ---------------------------------------------------------------------------
# Continual learning
# ---------------------------------------------------------------------------


def record_outcome(
    *,
    evidence_ids: list[str],
    accepted: bool,
    note: str = "",
) -> dict[str, Any]:
    """Reweight corpus passages after a design outcome.

    When an architect accepts a scheme, the passages that informed it become
    marginally more likely to surface next time; when a scheme is rejected they
    become less likely. The step is small and bounded on both sides, so a single
    project cannot distort retrieval, but a firm's accumulated preferences do
    steadily shape what the platform proposes.
    """
    index = get_index()
    delta = 0.12 if accepted else -0.09
    updated = sum(1 for doc_id in evidence_ids if index.boost(doc_id, delta))
    if updated:
        try:
            index.save()
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "learning.save_failed", level=30, error=str(exc))
    log_event(logger, "learning.outcome", accepted=accepted, updated=updated, note=note[:120])
    return {"updated": updated, "delta": delta, "accepted": accepted}


def add_project_memory(
    *,
    project_id: str,
    summary: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Index a completed project so future briefs can retrieve it as precedent.

    This is the mechanism behind "the system learns from previous experience":
    a practice's own delivered work becomes the corpus that grounds its next
    proposal, which no general-purpose model can replicate because it never sees
    that data.
    """
    index = get_index()
    document = Document(
        id=f"project_{project_id}",
        text=" ".join(summary.split()),
        source=f"Practice project archive / {project_id}",
        kind="precedent",
        tags=["own_work", *(tags or [])],
        metadata=metadata or {},
        # Own work starts above baseline: it is more relevant to this firm than
        # a generic reference passage.
        weight=1.35,
    )
    index.upsert(document)
    index.rebuild()
    try:
        index.save()
    except Exception as exc:  # noqa: BLE001
        log_event(logger, "learning.save_failed", level=30, error=str(exc))
    log_event(logger, "learning.project_indexed", project=project_id, corpus_size=index.size)
    return document.id


def corpus_stats() -> dict[str, Any]:
    return get_index().stats()
