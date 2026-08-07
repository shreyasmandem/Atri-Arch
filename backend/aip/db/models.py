"""Database schema.

Multi-tenant from the first line: every row that matters belongs to a `Firm`.
An architecture practice embedding the widget on its own website must never be
able to see another practice's projects, rates or learned critic weights - and
the learned weights are precisely the asset that makes the platform valuable to
each firm individually, so tenant isolation is a product requirement, not just a
security one.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Base(DeclarativeBase):
    pass


class Firm(Base):
    """An architecture practice using the platform."""

    __tablename__ = "firms"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uid("firm"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    contact_email: Mapped[str] = mapped_column(String(200), default="")
    locale: Mapped[str] = mapped_column(String(16), default="en-IN")
    region: Mapped[str] = mapped_column(String(16), default="IN-TN")

    #: Domains permitted to embed the widget. Empty means any, which is only
    #: appropriate during development.
    allowed_origins: Mapped[list] = mapped_column(JSON, default=list)
    #: Firm-specific rate schedule overriding the indicative one.
    rate_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Branding for the embedded widget.
    theme: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    monthly_design_quota: Mapped[int] = mapped_column(Integer, default=500)
    designs_this_month: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="firm", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="firm", cascade="all, delete-orphan")

    def origin_allowed(self, origin: str | None) -> bool:
        if not self.allowed_origins:
            return True
        if not origin:
            return False
        return any(origin.rstrip("/").endswith(allowed.rstrip("/")) for allowed in self.allowed_origins)


class ApiKey(Base):
    """A credential used by an embedded widget or a server integration."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uid("key"))
    firm_id: Mapped[str] = mapped_column(ForeignKey("firms.id", ondelete="CASCADE"), index=True)
    #: SHA-256 of the key. The plaintext is shown once at creation and never stored.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: First characters, so a user can identify which key a row refers to.
    prefix: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(120), default="")
    #: 'public' keys are safe to ship in browser JavaScript and are limited to
    #: client-facing operations; 'secret' keys carry full access.
    scope: Mapped[str] = mapped_column(String(16), default="public")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    firm: Mapped[Firm] = relationship(back_populates="api_keys")

    @staticmethod
    def generate(scope: str = "public") -> tuple[str, str, str]:
        """Return (plaintext, sha256 hash, prefix). Plaintext is never persisted."""
        import hashlib

        marker = "pk" if scope == "public" else "sk"
        raw = f"aip_{marker}_{secrets.token_urlsafe(32)}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return raw, digest, raw[:14]


class Project(Base):
    """A design project belonging to a firm."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uid("proj"))
    firm_id: Mapped[str] = mapped_column(ForeignKey("firms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="Untitled Project")
    status: Mapped[str] = mapped_column(String(32), default="draft")

    client_name: Mapped[str] = mapped_column(String(200), default="")
    client_email: Mapped[str] = mapped_column(String(200), default="")
    #: Where the brief came from: 'studio' (architect) or 'widget' (client).
    source: Mapped[str] = mapped_column(String(16), default="studio")

    brief: Mapped[dict] = mapped_column(JSON, default=dict)
    selected_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    vastu_report: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_estimate: Mapped[dict] = mapped_column(JSON, default=dict)

    #: Actual delivered cost, once known. This is what trains the calibration.
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_duration_months: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    firm: Mapped[Firm] = relationship(back_populates="projects")
    sessions: Mapped[list["DesignSession"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_projects_firm_created", "firm_id", "created_at"),)


class DesignSession(Base):
    """One execution of the design pipeline, kept for audit and replay."""

    __tablename__ = "design_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uid("sess"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    trace_id: Mapped[str] = mapped_column(String(32), index=True, default="")

    status: Mapped[str] = mapped_column(String(24), default="running")
    brief: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Full critic transcript. This is the explainability audit trail.
    critiques: Mapped[dict] = mapped_column(JSON, default=dict)
    consensus: Mapped[dict] = mapped_column(JSON, default=dict)

    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    model_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="sessions")


class ProjectFeedback(Base):
    """Architect or client judgement on a produced design.

    This table is the training signal for the whole learning loop: it updates
    critic reliability, reweights corpus passages, and calibrates the cost model.
    """

    __tablename__ = "project_feedback"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uid("fb"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(40), default="")
    plan_id: Mapped[str] = mapped_column(String(40), default="")

    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)   # 0-1
    author_role: Mapped[str] = mapped_column(String(24), default="architect")
    #: Per-axis judgement, e.g. {"daylight": 0.9, "vastu": 0.4}. Used to score
    #: each critic's prediction against a human verdict.
    axis_ratings: Mapped[dict] = mapped_column(JSON, default=dict)
    comment: Mapped[str] = mapped_column(Text, default="")
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CriticCalibrationRow(Base):
    """Learned reliability of one critic, for one firm."""

    __tablename__ = "critic_calibration"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uid("cal"))
    firm_id: Mapped[str] = mapped_column(ForeignKey("firms.id", ondelete="CASCADE"), index=True)
    critic_id: Mapped[str] = mapped_column(String(64), index=True)
    reliability: Mapped[float] = mapped_column(Float, default=0.8)
    observations: Mapped[int] = mapped_column(Integer, default=0)
    mean_brier: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (Index("ix_calibration_firm_critic", "firm_id", "critic_id", unique=True),)


def to_dict(row: Any) -> dict[str, Any]:
    """Serialise an ORM row, rendering datetimes as ISO strings."""
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        out[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return out
