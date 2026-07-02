"""Loads and validates the NIST questionnaire template from YAML."""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.models.enums import NistFunction, Weight

# backend/app/data/questionnaire_v1.yaml
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DEFAULT_FILE = _DATA_DIR / "questionnaire_v1.yaml"

_VALID_FUNCTIONS = {f.value for f in NistFunction}
_VALID_WEIGHTS = {w.value for w in Weight}


_VALID_OWNERS = {"platform", "use_case"}


@dataclass(frozen=True)
class ControlTemplate:
    key: str
    control_id: str
    nist_function: str
    weight: str
    is_ko: bool
    question: str
    evidence_needed: str | None
    gai_categories: tuple[str, ...]
    # Who can answer it: "platform" — inherent to the model / the cloud platform
    # hosting it (infra + governance team); "use_case" — depends on how THIS
    # deployment will be used (the consuming team).
    owner: str = "platform"


@dataclass(frozen=True)
class Questionnaire:
    version: int
    framework: str
    meta: dict  # framework_meta: name, rmf_version, effective_date, references
    controls: tuple[ControlTemplate, ...]

    @property
    def control_count(self) -> int:
        return len(self.controls)

    def as_snapshot(self) -> dict:
        """Serializable snapshot frozen into a Review for auditability."""
        return {
            "version": self.version,
            "framework": self.framework,
            "controls": [
                {
                    "key": c.key,
                    "control_id": c.control_id,
                    "nist_function": c.nist_function,
                    "weight": c.weight,
                    "is_ko": c.is_ko,
                    "question": c.question,
                    "evidence_needed": c.evidence_needed,
                    "gai_categories": list(c.gai_categories),
                    "owner": c.owner,
                }
                for c in self.controls
            ],
        }


def _validate(q: Questionnaire) -> None:
    keys = [c.key for c in q.controls]
    if len(keys) != len(set(keys)):
        dupes = {k for k in keys if keys.count(k) > 1}
        raise ValueError(f"Duplicate questionnaire control keys: {sorted(dupes)}")
    for c in q.controls:
        if c.nist_function not in _VALID_FUNCTIONS:
            raise ValueError(f"Control {c.key}: invalid nist_function {c.nist_function!r}")
        if c.weight not in _VALID_WEIGHTS:
            raise ValueError(f"Control {c.key}: invalid weight {c.weight!r}")
        if c.owner not in _VALID_OWNERS:
            raise ValueError(f"Control {c.key}: invalid owner {c.owner!r}")


def load_questionnaire(path: Path | None = None) -> Questionnaire:
    raw = yaml.safe_load((path or _DEFAULT_FILE).read_text())
    controls = tuple(
        ControlTemplate(
            key=c["key"],
            control_id=c["control_id"],
            nist_function=c["nist_function"],
            weight=c["weight"],
            is_ko=bool(c.get("is_ko", False)),
            question=c["question"],
            evidence_needed=c.get("evidence_needed"),
            gai_categories=tuple(c.get("gai_categories", []) or []),
            owner=c.get("owner", "platform"),
        )
        for c in raw["controls"]
    )
    q = Questionnaire(
        version=raw["version"],
        framework=raw["framework"],
        meta=raw.get("framework_meta", {}) or {},
        controls=controls,
    )
    _validate(q)
    return q


@functools.lru_cache
def get_questionnaire() -> Questionnaire:
    """Cached current questionnaire template."""
    return load_questionnaire()


@functools.lru_cache
def owner_of(control_key: str) -> str:
    """Answering team for a control key ("platform" | "use_case"). Unknown keys
    (e.g. from an older questionnaire snapshot) default to "platform"."""
    for c in get_questionnaire().controls:
        if c.key == control_key:
            return c.owner
    return "platform"
