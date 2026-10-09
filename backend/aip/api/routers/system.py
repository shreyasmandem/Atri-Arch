"""Health, capability discovery and onboarding status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from aip.api.schemas import HealthResponse
from aip.api.security import Principal, get_principal
from aip.core.config import get_settings
from aip.core.llm import get_router as get_llm_router
from aip.core.providers import provider_setup_report

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from aip import __version__
    from aip.rag.corpus import corpus_summary

    settings = get_settings()
    configured = settings.configured_providers()
    llm = get_llm_router()
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment,
        providers_configured=configured,
        # 'ollama' alone means local inference only, which works but is slower
        # and weaker than the hosted free tiers.
        degraded_mode=configured in ([], ["ollama"]),
        corpus=corpus_summary(),
        total_model_cost_usd=llm.ledger.total_cost_usd,
    )


@router.get("/providers")
async def providers() -> dict[str, Any]:
    """Which free model providers are configured, and how to enable the rest.

    Powers the onboarding screen. Every provider listed has a genuine free tier;
    the platform runs with none of them configured, better with one, and best
    with several, because the critic ensemble draws its independence from having
    several different model families available.
    """
    settings = get_settings()
    report = provider_setup_report(settings)
    configured = [row for row in report if row["configured"]]
    return {
        "configured_count": len(configured),
        "total_count": len(report),
        "ensemble_diversity": min(1.0, len(configured) / 4),
        "recommendation": _recommendation(len(configured)),
        "providers": report,
    }


def _recommendation(count: int) -> str:
    if count == 0:
        return (
            "No provider is configured. Every analytical capability - geometry, "
            "daylight, ventilation, code compliance, Vastu reasoning and cost - "
            "works fully without one. Add a free key to enable generated "
            "commentary and the judgement-based critics."
        )
    if count == 1:
        return (
            "One provider configured. The pipeline works, but the critic "
            "ensemble is drawing every judgement from a single model family, so "
            "its members make correlated mistakes. Add a second free provider to "
            "get genuinely independent opinions."
        )
    if count < 4:
        return (
            f"{count} providers configured. Ensemble diversity is reasonable. "
            f"Adding more raises resilience to any one free tier being exhausted."
        )
    return (
        f"{count} providers configured. Full ensemble diversity and strong "
        f"failover; the platform will stay available even if several free tiers "
        f"are rate-limited at once."
    )


@router.get("/capabilities")
async def capabilities(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """Machine-readable description of what this deployment can do."""
    from aip.agents.critics import committee_charter
    from aip.engines.vastu.knowledge import corpus_statistics

    settings = get_settings()
    has_generative = bool(settings.configured_providers())
    return {
        "phases": {
            "architecture": {
                "available": True,
                "features": [
                    "floorplan generation", "elevations", "sections", "roof layout",
                    "column grid", "stair design", "daylight optimisation",
                    "ventilation optimisation", "privacy analysis",
                    "accessibility checking", "circulation analysis",
                ],
            },
            "interior": {
                "available": True,
                "features": [
                    "furniture placement", "furniture schedule", "palette generation",
                    "material selection", "lighting design", "room redesign brief",
                ],
                "note": (
                    "Photorealistic renders require an image provider; layout, "
                    "specification and costing are computed locally."
                ),
            },
            "vastu": {
                "available": True,
                "features": [
                    "explainable rule evaluation", "traditional/modern reconciliation",
                    "counterfactual remedies", "conflict resolution", "provenance citations",
                ],
                "corpus": corpus_statistics(),
            },
            "cost": {
                "available": True,
                "features": [
                    "quantity takeoff", "bill of quantities", "Monte Carlo risk simulation",
                    "cash flow forecast", "delay probability", "firm-specific calibration",
                ],
            },
            "experience": {
                "available": True,
                "features": [
                    "3D model (GLB)", "OBJ export", "WebXR VR walkthrough",
                    "AR placement", "voice narration script", "budget simulation",
                ],
            },
        },
        "committee": committee_charter(),
        "generative_critics_active": has_generative,
        "zero_cost": True,
        "scope": principal.scope,
    }


@router.get("/vastu/calibration")
async def vastu_calibration_status() -> dict[str, Any]:
    """Inspect the Vastu weight calibration subsystem status and rule cards."""
    from aip.engines.vastu.calibration import cards_from_corpus
    cards = cards_from_corpus()
    return {
        "status": "active",
        "calibrated_rules_count": len(cards),
        "trainable_parameter": "rule_weight_w_r",
        "frozen_invariants": ["modern_validity", "provenance", "stance_t"],
        "cards": [
            {
                "rule_id": c.rule_id,
                "provenance": c.provenance,
                "modern_validity": c.modern_validity,
                "prior_weight": c.prior_weight,
            }
            for c in cards
        ],
    }
