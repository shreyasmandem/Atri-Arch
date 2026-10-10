"""Tenant administration, feedback capture and the learning loop."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aip.api.schemas import (
    ActualsRequest,
    ApiKeyResponse,
    FeedbackRequest,
    FirmCreateRequest,
)
from aip.api.security import Principal, get_principal, require_secret
from aip.core.logging import get_logger, log_event
from aip.db.models import (
    ApiKey,
    CriticCalibrationRow,
    DesignSession,
    Firm,
    Project,
    ProjectFeedback,
    to_dict,
)
from aip.db.session import get_session

logger = get_logger("aip.api.admin")
router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------------------
# Firms and keys
# ---------------------------------------------------------------------------


@router.post("/firms", response_model=dict, status_code=201)
async def create_firm(
    payload: FirmCreateRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> dict[str, Any]:
    existing = await session.execute(select(Firm).where(Firm.slug == payload.slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Slug '{payload.slug}' is already taken.")

    firm = Firm(
        name=payload.name,
        slug=payload.slug,
        contact_email=payload.contact_email,
        region=payload.region,
        allowed_origins=payload.allowed_origins,
    )
    session.add(firm)
    await session.flush()
    log_event(logger, "firm.created", firm=firm.id, slug=firm.slug)
    return to_dict(firm)


@router.get("/firms/me")
async def get_my_firm(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    firm = to_dict(principal.firm)
    firm.pop("rate_overrides", None)      # potentially commercially sensitive
    return {**firm, "scope": principal.scope}


@router.post("/firms/{firm_id}/keys", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    firm_id: str,
    label: str = Query(default=""),
    scope: str = Query(default="public", pattern="^(public|secret)$"),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> ApiKeyResponse:
    """Mint an API key. The plaintext is returned once and never stored."""
    if principal.firm.id != firm_id:
        raise HTTPException(status_code=403, detail="You can only create keys for your own firm.")

    firm = await session.get(Firm, firm_id)
    if firm is None:
        raise HTTPException(status_code=404, detail="Firm not found.")

    raw, digest, prefix = ApiKey.generate(scope)
    api_key = ApiKey(
        firm_id=firm_id, key_hash=digest, prefix=prefix, label=label, scope=scope
    )
    session.add(api_key)
    await session.flush()
    log_event(logger, "apikey.created", firm=firm_id, scope=scope, prefix=prefix)

    return ApiKeyResponse(
        id=api_key.id,
        key=raw,
        prefix=prefix,
        scope=scope,
        label=label,
        created_at=api_key.created_at.isoformat(),
    )


@router.get("/firms/{firm_id}/keys")
async def list_api_keys(
    firm_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> list[dict[str, Any]]:
    if principal.firm.id != firm_id:
        raise HTTPException(status_code=403, detail="You can only list your own firm's keys.")
    rows = (
        await session.execute(select(ApiKey).where(ApiKey.firm_id == firm_id))
    ).scalars().all()
    # key_hash is deliberately never returned.
    return [
        {
            "id": r.id, "prefix": r.prefix, "scope": r.scope, "label": r.label,
            "active": r.active,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> None:
    api_key = await session.get(ApiKey, key_id)
    if api_key is None or api_key.firm_id != principal.firm.id:
        raise HTTPException(status_code=404, detail="Key not found.")
    api_key.active = False
    log_event(logger, "apikey.revoked", key=key_id, firm=principal.firm.id)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.get("/projects")
async def list_projects(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Project)
            .where(Project.firm_id == principal.firm.id)
            .order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {
        "total": len(rows),
        "projects": [
            {
                "id": p.id, "name": p.name, "status": p.status,
                "client_name": p.client_name, "source": p.source,
                "created_at": p.created_at.isoformat(),
                "vastu_score": (p.vastu_report or {}).get("score"),
                "cost_total": (p.cost_estimate or {}).get("total"),
                "built_area": (p.selected_plan or {}).get("total_built_area"),
            }
            for p in rows
        ],
    }


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if project is None or project.firm_id != principal.firm.id:
        raise HTTPException(status_code=404, detail="Project not found.")

    sessions = (
        await session.execute(
            select(DesignSession)
            .where(DesignSession.project_id == project_id)
            .order_by(DesignSession.created_at.desc())
        )
    ).scalars().all()

    return {
        **to_dict(project),
        "sessions": [
            {
                "id": s.id, "status": s.status, "trace_id": s.trace_id,
                "duration_ms": s.duration_ms, "degraded": s.degraded,
                "created_at": s.created_at.isoformat(),
                "consensus": s.consensus,
            }
            for s in sessions
        ],
    }


@router.get("/sessions/{session_id}/audit")
async def get_session_audit(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> dict[str, Any]:
    """Full critic transcript for one design run.

    This is the explainability record: every verdict, every piece of evidence,
    every score, and how consensus was reached. It is what makes a
    recommendation defensible to a client, an approving authority, or a reviewer
    assessing the research claim.
    """
    design_session = await session.get(DesignSession, session_id)
    if design_session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    project = await session.get(Project, design_session.project_id)
    if project is None or project.firm_id != principal.firm.id:
        raise HTTPException(status_code=404, detail="Session not found.")

    return {
        "session_id": design_session.id,
        "trace_id": design_session.trace_id,
        "status": design_session.status,
        "brief": design_session.brief,
        "critiques": design_session.critiques,
        "consensus": design_session.consensus,
        "result": design_session.result,
        "duration_ms": design_session.duration_ms,
        "model_cost_usd": design_session.model_cost_usd,
        "degraded": design_session.degraded,
        "created_at": design_session.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Learning loop
# ---------------------------------------------------------------------------


@router.post("/feedback", status_code=201)
async def submit_feedback(
    payload: FeedbackRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    """Record a human verdict and use it to update every learned component.

    Three things move: each critic's reliability is scored against the human's
    per-axis rating, the corpus passages that informed the design are reweighted,
    and the project is marked accepted or rejected. This is the mechanism behind
    the platform improving for a specific practice over time.
    """
    project = await session.get(Project, payload.project_id)
    if project is None or project.firm_id != principal.firm.id:
        raise HTTPException(status_code=404, detail="Project not found.")

    feedback = ProjectFeedback(
        project_id=payload.project_id,
        session_id=payload.session_id,
        plan_id=payload.plan_id,
        accepted=payload.accepted,
        rating=payload.rating,
        axis_ratings=payload.axis_ratings,
        comment=payload.comment,
        author_role=payload.author_role,
        evidence_ids=payload.evidence_ids,
    )
    session.add(feedback)
    project.status = "accepted" if payload.accepted else "revision_requested"

    critics_updated = 0
    if payload.session_id and payload.axis_ratings:
        critics_updated = await _calibrate_critics(
            session, principal.firm.id, payload.session_id, payload.plan_id, payload.axis_ratings
        )

    corpus_updated = 0
    if payload.evidence_ids:
        from aip.rag.retriever import record_outcome

        corpus_updated = record_outcome(
            evidence_ids=payload.evidence_ids, accepted=payload.accepted, note=payload.comment
        )["updated"]

    log_event(
        logger, "feedback.recorded",
        project=payload.project_id, accepted=payload.accepted,
        critics_updated=critics_updated, corpus_updated=corpus_updated,
    )
    return {
        "feedback_id": feedback.id,
        "critics_recalibrated": critics_updated,
        "corpus_passages_reweighted": corpus_updated,
    }


async def _calibrate_critics(
    session: AsyncSession,
    firm_id: str,
    session_id: str,
    plan_id: str,
    axis_ratings: dict[str, float],
) -> int:
    """Score each critic's prediction against the human verdict on its own axis."""
    design_session = await session.get(DesignSession, session_id)
    if design_session is None or not design_session.critiques:
        return 0

    critiques = design_session.critiques.get(plan_id) or next(
        iter(design_session.critiques.values()), []
    )

    updated = 0
    for critique in critiques:
        axis = critique.get("axis")
        if axis not in axis_ratings:
            continue
        predicted = float(critique.get("score", 0.5))
        actual = float(axis_ratings[axis])
        critic_id = critique.get("critic_id", "")
        if not critic_id:
            continue

        row = (
            await session.execute(
                select(CriticCalibrationRow).where(
                    CriticCalibrationRow.firm_id == firm_id,
                    CriticCalibrationRow.critic_id == critic_id,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            # Column defaults are applied by the database at INSERT, so a row
            # that has only been added to the session still has None in every
            # defaulted field. Seed them explicitly rather than reading None.
            row = CriticCalibrationRow(
                firm_id=firm_id, critic_id=critic_id,
                reliability=0.8, observations=0, mean_brier=0.0,
            )
            session.add(row)

        from aip.agents.consensus import CriticCalibration

        observations = row.observations or 0
        calibration = CriticCalibration(
            critic_id=critic_id,
            reliability=row.reliability if row.reliability is not None else 0.8,
            observations=observations,
            brier_sum=(row.mean_brier or 0.0) * max(1, observations),
        )
        calibration.observe(predicted, actual)

        row.reliability = calibration.reliability
        row.observations = calibration.observations
        row.mean_brier = calibration.mean_brier
        updated += 1
    return updated


@router.post("/actuals", status_code=201)
async def submit_actuals(
    payload: ActualsRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> dict[str, Any]:
    """Record the delivered cost and recalibrate the estimator for this firm.

    The calibration factor is an exponential moving average of the ratio between
    what the platform predicted and what the project actually cost. A practice
    that consistently builds 8% above the indicative schedule will, after a few
    projects, receive estimates that already include that 8%.
    """
    project = await session.get(Project, payload.project_id)
    if project is None or project.firm_id != principal.firm.id:
        raise HTTPException(status_code=404, detail="Project not found.")

    predicted = float((project.cost_estimate or {}).get("total") or 0.0)
    if predicted <= 0:
        raise HTTPException(
            status_code=409,
            detail="This project has no cost estimate to calibrate against.",
        )

    project.actual_cost = payload.actual_cost
    project.actual_duration_months = payload.actual_duration_months

    ratio = payload.actual_cost / predicted
    # Clamp before blending so one unusual project cannot distort the model.
    ratio = max(0.55, min(1.85, ratio))

    settings = dict(principal.firm.settings or {})
    current = float(settings.get("cost_calibration", 1.0))
    observations = int(settings.get("cost_observations", 0))
    alpha = 0.25 if observations < 6 else 0.12
    updated = (1 - alpha) * current + alpha * ratio

    settings["cost_calibration"] = round(updated, 4)
    settings["cost_observations"] = observations + 1
    principal.firm.settings = settings

    log_event(
        logger, "actuals.recorded",
        project=payload.project_id, ratio=round(ratio, 3),
        calibration=settings["cost_calibration"],
    )
    return {
        "project_id": project.id,
        "predicted": predicted,
        "actual": payload.actual_cost,
        "ratio": round(ratio, 4),
        "calibration_factor": settings["cost_calibration"],
        "observations": settings["cost_observations"],
        "note": (
            "Future estimates for this practice are multiplied by the "
            "calibration factor, which converges as more completed projects "
            "are recorded."
        ),
    }


@router.get("/learning/status")
async def learning_status(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> dict[str, Any]:
    """What the platform has learned about this practice so far."""
    from aip.rag.retriever import corpus_stats

    rows = (
        await session.execute(
            select(CriticCalibrationRow).where(CriticCalibrationRow.firm_id == principal.firm.id)
        )
    ).scalars().all()

    settings = principal.firm.settings or {}
    return {
        "firm": principal.firm.name,
        "critic_calibration": [
            {
                "critic_id": r.critic_id,
                "reliability": round(r.reliability, 4),
                "observations": r.observations,
                "mean_brier": round(r.mean_brier, 4),
            }
            for r in sorted(rows, key=lambda r: -r.reliability)
        ],
        "cost_calibration": {
            "factor": settings.get("cost_calibration", 1.0),
            "observations": settings.get("cost_observations", 0),
        },
        "corpus": corpus_stats(),
        "projects_designed": principal.firm.designs_this_month,
    }


@router.post("/learning/index-project", status_code=201)
async def index_project(
    project_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_secret),
) -> dict[str, Any]:
    """Add a completed project to the retrieval corpus as firm precedent."""
    project = await session.get(Project, project_id)
    if project is None or project.firm_id != principal.firm.id:
        raise HTTPException(status_code=404, detail="Project not found.")

    from aip.rag.retriever import add_project_memory

    plan = project.selected_plan or {}
    brief = project.brief or {}
    summary = (
        f"{project.name}: {brief.get('kind', 'residence')} of "
        f"{plan.get('total_built_area', 0):.0f} square metres on a "
        f"{(brief.get('site') or {}).get('plot_area', 0):.0f} square metre plot in "
        f"{(brief.get('site') or {}).get('locality', 'unknown location')}. "
        f"Style {plan.get('style', 'contemporary')}. "
        f"Vastu score {(project.vastu_report or {}).get('score', 'not assessed')}. "
        f"Delivered cost {project.actual_cost or (project.cost_estimate or {}).get('total', 0):,.0f}. "
        f"Rooms: "
        + ", ".join(
            f"{r.get('name', '')} {r.get('area_m2', 0):.0f} m2"
            for r in (plan.get("room_summary") or [])[:14]
        )
    )
    document_id = add_project_memory(
        project_id=project.id,
        summary=summary,
        tags=[str(brief.get("kind", "residence")), plan.get("style", "contemporary")],
        metadata={"firm_id": principal.firm.id, "project_id": project.id},
    )
    return {"document_id": document_id, "indexed": True}
