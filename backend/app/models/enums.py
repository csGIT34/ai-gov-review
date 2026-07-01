"""String-valued enums (stored as plain strings for portability).

Kept as `str` subclasses so they serialize cleanly and compare to raw strings.
"""
from __future__ import annotations

from enum import Enum


class Cloud(str, Enum):
    AZURE = "azure"
    GCP = "gcp"


class ReviewState(str, Enum):
    DISCOVERED = "discovered"
    PENDING_REVIEW = "pending_review"
    IN_REVIEW = "in_review"
    SCORED = "scored"
    APPROVED = "approved"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    REJECTED = "rejected"


# Terminal states a decision produces.
DECISION_STATES = {
    ReviewState.APPROVED,
    ReviewState.APPROVED_WITH_CONDITIONS,
    ReviewState.REJECTED,
}


class ReviewTrigger(str, Enum):
    MANUAL = "manual"
    AUTO_DISCOVERY = "auto_discovery"
    VERSION_CHANGE = "version_change"
    REREVIEW = "rereview"


class Answer(str, Enum):
    YES = "yes"
    PARTIAL = "partial"
    NO = "no"
    UNKNOWN = "unknown"


class Weight(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NistFunction(str, Enum):
    GOVERN = "GOVERN"
    MAP = "MAP"
    MEASURE = "MEASURE"
    MANAGE = "MANAGE"


class Decision(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    REJECT = "reject"


class Role(str, Enum):
    REVIEWER = "reviewer"
    APPROVER = "approver"
    ADMIN = "admin"


class ModelStatus(str, Enum):
    ACTIVE = "active"
    DISAPPEARED = "disappeared"


class AnswerSource(str, Enum):
    AUTO = "auto"  # deterministic fact from the cloud API — accepted
    SUGGESTED = "suggested"  # from provider docs — needs human confirmation
    HUMAN = "human"  # set or confirmed by a reviewer
