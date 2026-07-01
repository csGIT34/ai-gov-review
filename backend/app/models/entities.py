"""ORM entities for the governance review domain.

Relationships map: DiscoverySource 1-* Model 1-* Review 1-* ControlResponse,
Review 1-* RiskScore, Review 1-* ApprovalDecision. AuditLog is standalone and
append-only (enforced by a Postgres trigger in migration 0002).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, TimestampMixin, UUIDPKMixin, utcnow


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # OIDC subject (M10) or null for local accounts.
    auth_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # List of role strings: reviewer | approver | admin.
    roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiscoverySource(UUIDPKMixin, TimestampMixin, Base):
    """A configured cloud scope we query on demand to populate review dropdowns."""

    __tablename__ = "discovery_sources"

    cloud: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Azure: tenant/subscription/mgmt-group id. GCP: organizations/{n} or project.
    scope: Mapped[str] = mapped_column(String(500), nullable=False)
    # Name/reference of the managed identity or SA — NEVER the secret itself.
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_queried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_query_status: Mapped[str | None] = mapped_column(String(500), nullable=True)

    models: Mapped[list["Model"]] = relationship(back_populates="discovery_source")


class Model(UUIDPKMixin, TimestampMixin, Base):
    """A discovered/selected model — the unit of governance."""

    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint("resource_id", "model_version", name="uq_model_resource_version"),
    )

    discovery_source_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("discovery_sources.id"), nullable=True
    )
    cloud: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    vendor: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_format: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Canonical cloud resource id — the dedup key (with model_version).
    resource_id: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    resource_kind: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subscription_or_project: Mapped[str | None] = mapped_column(String(300), nullable=True)
    resource_group: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # A model is deployed across many regions (for quota) — its residency footprint.
    regions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    provisioning_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    cloud_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cloud_last_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    # Cloud resource properties used to auto-answer controls (region, content
    # filter, network exposure, encryption, versioning, etc.). Populated by the
    # discovery driver; drives the auto-answer engine.
    facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Denormalized pointers for fast list views (no FK to avoid a cycle).
    current_review_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    latest_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)

    discovery_source: Mapped["DiscoverySource | None"] = relationship(back_populates="models")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )


class Review(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "reviews"

    model_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("models.id"), nullable=False, index=True
    )
    framework: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)

    assigned_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )
    assigned_approver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Frozen questionnaire template + weights used for THIS review, so later
    # template edits never retroactively change what was signed off.
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    model: Mapped["Model"] = relationship(back_populates="reviews")
    controls: Mapped[list["ControlResponse"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )
    scores: Mapped[list["RiskScore"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["ApprovalDecision"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class ControlResponse(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "control_responses"

    review_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("reviews.id"), nullable=False, index=True
    )
    # Stable per-question key from the questionnaire template (control_id can repeat).
    control_key: Mapped[str] = mapped_column(String(60), nullable=False)
    control_id: Mapped[str] = mapped_column(String(40), nullable=False)
    nist_function: Mapped[str] = mapped_column(String(20), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_needed: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[str] = mapped_column(String(10), nullable=False)
    gai_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_ko: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Null until answered.
    answer: Mapped[str | None] = mapped_column(String(10), nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Auto-answer provenance. answer_source: auto (deterministic fact, accepted) |
    # suggested (from provider docs, needs human confirmation) | human.
    answer_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    auto_answer: Mapped[str | None] = mapped_column(String(10), nullable=True)
    auto_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)

    review: Mapped["Review"] = relationship(back_populates="controls")


class RiskScore(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "risk_scores"

    review_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("reviews.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    # {"GOVERN": 0.0..1.0, "MAP": ..., "MEASURE": ..., "MANAGE": ...}
    function_deficits: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # [{"type": "high_weight_no"|"ko_fail", "control_id": ..., "reason": ...}]
    triggered_gates: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    review: Mapped["Review"] = relationship(back_populates="scores")


class ApprovalDecision(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "approval_decisions"

    review_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("reviews.id"), nullable=False, index=True
    )
    # The exact score snapshot the decision was made against.
    risk_score_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("risk_scores.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    risk_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )
    decided_by_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    # Set when an admin overrode a gate-forced tier (e.g. approved a Tier 4).
    overridden_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    review: Mapped["Review"] = relationship(back_populates="decisions")


class GovernancePolicy(UUIDPKMixin, TimestampMixin, Base):
    """Singleton org policy for auto-answer determinations (admin-editable).

    Holds the policy inputs the auto-answer engine compares cloud facts against —
    currently the approved data-residency regions. A DiscoverySource may override
    per scope via its `config`.
    """

    __tablename__ = "governance_policy"

    approved_regions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    # Framework-freshness governance: when the questionnaire was last confirmed
    # to still match the current NIST release, by whom, and how often it's due.
    framework_last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    framework_reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    framework_review_interval_days: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    framework_review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(UUIDPKMixin, Base):
    """Append-only audit trail. No updated_at; rows are never mutated."""

    __tablename__ = "audit_log"

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Optional tamper-evident hash chain.
    hash_prev: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_self: Mapped[str | None] = mapped_column(String(64), nullable=True)
