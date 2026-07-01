"""Pydantic request/response schemas for the API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.nist import control_title, control_url
from app.services.scoring import TIER_LABELS


class Schema(BaseModel):
    # model_* field names (model_name, model_version, ...) are legitimate here.
    model_config = ConfigDict(protected_namespaces=())


class ORMModel(Schema):
    model_config = ConfigDict(from_attributes=True)


# --- users ---------------------------------------------------------------------

class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str
    roles: list[str]
    is_active: bool


# --- discovery -----------------------------------------------------------------

class SourceOut(ORMModel):
    id: uuid.UUID
    cloud: str
    display_name: str
    scope: str
    enabled: bool


class SourceCreate(Schema):
    cloud: str
    display_name: str
    scope: str
    credential_ref: str | None = None
    config: dict | None = None


class PolicyOut(ORMModel):
    approved_regions: dict[str, list[str]]  # {"azure": [...], "gcp": [...]}
    updated_at: datetime


class PolicyUpdate(Schema):
    approved_regions: dict[str, list[str]]


class FrameworkReferenceOut(Schema):
    label: str | None = None
    doc: str | None = None
    url: str | None = None


class FrameworkStatusOut(Schema):
    # What the questions implement (from the questionnaire — single source of truth).
    id: str
    name: str
    rmf_version: str | None
    effective_date: str | None
    references: list[FrameworkReferenceOut]
    questionnaire_version: int
    control_count: int
    # Admin review-freshness record.
    last_reviewed_at: datetime | None
    reviewed_by: str | None
    review_interval_days: int
    next_review_due: datetime | None
    overdue: bool
    notes: str | None
    # Registry comparison: is a newer NIST release known than the one we implement?
    update_available: bool
    latest_known_version: str


class FrameworkReviewIn(Schema):
    notes: str | None = None
    interval_days: int | None = None


class UpdateCheckOut(Schema):
    implemented_version: str
    latest_known_version: str
    latest_published: str
    latest_label: str
    latest_url: str
    latest_notes: str
    up_to_date: bool
    checked_at: datetime


class DiscoveredModelOut(Schema):
    vendor: str
    model_name: str
    model_version: str | None = None
    model_format: str | None = None
    resource_id: str
    resource_kind: str | None = None
    regions: list[str] = []
    sku: str | None = None
    endpoint: str | None = None
    provisioning_state: str | None = None
    label: str


# --- models --------------------------------------------------------------------

class ModelOut(ORMModel):
    id: uuid.UUID
    cloud: str
    vendor: str
    model_name: str
    model_version: str | None
    resource_id: str
    regions: list[str]
    status: str
    latest_score: float | None
    latest_tier: int | None
    current_review_id: uuid.UUID | None
    first_seen_at: datetime
    last_seen_at: datetime


class ModelDetailOut(ModelOut):
    model_format: str | None
    resource_kind: str | None
    subscription_or_project: str | None
    resource_group: str | None
    sku: str | None
    endpoint: str | None
    provisioning_state: str | None
    discovery_source_id: uuid.UUID | None


# --- scoring -------------------------------------------------------------------

class RiskScoreOut(ORMModel):
    id: uuid.UUID
    review_id: uuid.UUID
    computed_at: datetime
    overall_score: float
    tier: int
    tier_label: str | None = None
    function_deficits: dict[str, float]
    triggered_gates: list[dict]
    is_current: bool

    @model_validator(mode="after")
    def _fill_tier_label(self) -> "RiskScoreOut":
        if self.tier_label is None:
            self.tier_label = TIER_LABELS.get(self.tier)
        return self


class QuestionnaireControlOut(Schema):
    key: str
    control_id: str
    nist_function: str
    weight: str
    is_ko: bool
    question: str
    evidence_needed: str | None
    gai_categories: list[str]


class QuestionnaireOut(Schema):
    version: int
    framework: str
    controls: list[QuestionnaireControlOut]


# --- reviews -------------------------------------------------------------------

class ReviewCreate(Schema):
    """Start a review from a discovered selection, or re-review an existing model."""

    # Discovered selection (cascading dropdowns): source -> vendor -> model.
    source_id: uuid.UUID | None = None
    vendor: str | None = None
    resource_id: str | None = None
    model_version: str | None = None
    # Or re-review an existing model directly.
    model_id: uuid.UUID | None = None
    trigger: str | None = None

    @model_validator(mode="after")
    def _require_selection(self) -> "ReviewCreate":
        if self.model_id is None and not (self.source_id and self.vendor and self.resource_id):
            raise ValueError(
                "Provide model_id, or (source_id, vendor, resource_id) for a discovered selection."
            )
        return self


class AssignIn(Schema):
    reviewer_id: uuid.UUID | None = None
    approver_id: uuid.UUID | None = None


class ControlAnswerIn(Schema):
    answer: str = Field(description="yes | partial | no | unknown")
    evidence_url: str | None = None
    evidence_note: str | None = None


class ControlOut(ORMModel):
    id: uuid.UUID
    control_key: str
    control_id: str
    nist_control: str | None = None  # exact subcategory statement, e.g. "GOVERN 6.1 — ..."
    nist_url: str | None = None  # NIST Playbook link for the control's function
    nist_function: str
    question_text: str
    evidence_needed: str | None
    weight: str
    gai_categories: list[str]
    is_ko: bool
    answer: str | None
    evidence_url: str | None
    evidence_note: str | None
    answered_at: datetime | None
    answered_by_id: uuid.UUID | None
    answer_source: str | None
    auto_answer: str | None
    auto_rationale: str | None
    auto_confidence: str | None

    @model_validator(mode="after")
    def _fill_nist_control(self) -> "ControlOut":
        if self.nist_control is None:
            self.nist_control = control_title(self.control_id)
        if self.nist_url is None:
            self.nist_url = control_url(self.control_id)
        return self


class ReviewOut(ORMModel):
    id: uuid.UUID
    model_id: uuid.UUID
    framework: str
    state: str
    trigger: str
    assigned_reviewer_id: uuid.UUID | None
    assigned_approver_id: uuid.UUID | None
    opened_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None


class ReviewDetailOut(ReviewOut):
    model: ModelOut
    controls: list[ControlOut]
    current_score: RiskScoreOut | None = None


class SubmitResultOut(Schema):
    review: ReviewOut
    score: RiskScoreOut


# --- approvals -----------------------------------------------------------------

class DecisionIn(Schema):
    decision: str = Field(description="approve | approve_with_conditions | reject")
    justification: str
    conditions: str | None = None
    risk_owner_id: uuid.UUID | None = None
    override_reason: str | None = None


class DecisionOut(ORMModel):
    id: uuid.UUID
    review_id: uuid.UUID
    risk_score_id: uuid.UUID
    decision: str
    conditions: str | None
    justification: str
    risk_owner_id: uuid.UUID | None
    decided_by_id: uuid.UUID
    decided_at: datetime
    overridden_tier: int | None
    override_reason: str | None


# --- audit ---------------------------------------------------------------------

class AuditOut(ORMModel):
    id: uuid.UUID
    ts: datetime
    actor_id: uuid.UUID | None
    actor_type: str
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_ip: str | None
