"""Pure NIST AI RMF scoring engine.

Deterministic, no I/O, no DB. Given a set of answered controls it produces a
0-100 risk score (higher = riskier), per-function deficits, a Tier (1-4), and
the list of gates that fired.

Scoring model (from the NIST AI RMF design):
    weight w:   low=1, medium=2, high=3
    answer a:   yes=1.0, partial=0.5, no=0.0, unknown/unanswered=0.0
                (opacity counts as risk — never treated as N/A)
    per item risk deficit  d_i = w_i * (1 - a_i)
    overall_score = 100 * sum(d_i) / sum(w_i)
    function_deficit[f] = sum(d_i in f) / sum(w_i in f)   -> 0..1

Gate overrides (independent of the average):
    * any HIGH-weight control answered No/Unknown  -> minimum Tier 3
    * any KO control answered No/Unknown           -> Tier 4 (block)

Final tier = max(score-band tier, gate-forced tier).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Weight label -> numeric weight.
WEIGHT_VALUES: dict[str, int] = {"low": 1, "medium": 2, "high": 3}

# Answer -> normalized satisfaction score in [0, 1]. Unknown == No == 0.0.
ANSWER_VALUES: dict[str, float] = {"yes": 1.0, "partial": 0.5, "no": 0.0, "unknown": 0.0}

# Answers that constitute a "failure" for gating purposes.
FAILING_ANSWERS: frozenset[str] = frozenset({"no", "unknown"})

TIER_LABELS: dict[int, str] = {
    1: "Low / Approved",
    2: "Moderate / Approved with Conditions",
    3: "Elevated / Governance Review Required",
    4: "High / Rejected — Blocked",
}


@dataclass(frozen=True)
class ScoredControl:
    """The minimal control shape the engine needs (subset of ControlResponse)."""

    key: str
    control_id: str
    nist_function: str
    weight: str
    is_ko: bool
    answer: str | None  # yes | partial | no | unknown | None (unanswered)


@dataclass
class RiskResult:
    overall_score: float
    tier: int
    tier_label: str
    function_deficits: dict[str, float]
    triggered_gates: list[dict] = field(default_factory=list)
    answered: int = 0
    total: int = 0

    @property
    def is_complete(self) -> bool:
        return self.total > 0 and self.answered == self.total


def weight_value(weight: str) -> int:
    return WEIGHT_VALUES[weight]


def answer_value(answer: str | None) -> float:
    """Unanswered controls are treated as Unknown (0.0) for scoring."""
    if answer is None:
        return 0.0
    return ANSWER_VALUES[answer]


def tier_from_score(score: float) -> int:
    """Score-band tier before gate overrides. Bands: 0-20 / 21-40 / 41-60 / 61-100."""
    if score <= 20:
        return 1
    if score <= 40:
        return 2
    if score <= 60:
        return 3
    return 4


def score_controls(controls: list[ScoredControl]) -> RiskResult:
    """Compute the risk result for a set of controls. Pure function."""
    if not controls:
        return RiskResult(
            overall_score=0.0,
            tier=1,
            tier_label=TIER_LABELS[1],
            function_deficits={},
            triggered_gates=[],
            answered=0,
            total=0,
        )

    total_weight = 0
    total_deficit = 0.0
    per_fn_weight: dict[str, int] = {}
    per_fn_deficit: dict[str, float] = {}
    gates: list[dict] = []
    answered = 0

    for c in controls:
        w = weight_value(c.weight)
        a = answer_value(c.answer)
        deficit = w * (1.0 - a)

        total_weight += w
        total_deficit += deficit
        per_fn_weight[c.nist_function] = per_fn_weight.get(c.nist_function, 0) + w
        per_fn_deficit[c.nist_function] = per_fn_deficit.get(c.nist_function, 0.0) + deficit

        if c.answer is not None:
            answered += 1

        failing = c.answer in FAILING_ANSWERS
        if c.is_ko and failing:
            gates.append(
                {
                    "type": "ko_fail",
                    "control_id": c.control_id,
                    "control_key": c.key,
                    "answer": c.answer,
                    "reason": f"Knock-out control '{c.key}' ({c.control_id}) answered {c.answer}.",
                }
            )
        elif c.weight == "high" and failing:
            gates.append(
                {
                    "type": "high_weight_no",
                    "control_id": c.control_id,
                    "control_key": c.key,
                    "answer": c.answer,
                    "reason": f"High-weight control '{c.key}' ({c.control_id}) answered {c.answer}.",
                }
            )

    overall_score = round(100.0 * total_deficit / total_weight, 1) if total_weight else 0.0
    function_deficits = {
        fn: round(per_fn_deficit[fn] / per_fn_weight[fn], 4) for fn in per_fn_weight
    }

    # Tier: max of score band and any gate-forced floor.
    tier = tier_from_score(overall_score)
    if any(g["type"] == "high_weight_no" for g in gates):
        tier = max(tier, 3)
    if any(g["type"] == "ko_fail" for g in gates):
        tier = 4

    return RiskResult(
        overall_score=overall_score,
        tier=tier,
        tier_label=TIER_LABELS[tier],
        function_deficits=function_deficits,
        triggered_gates=gates,
        answered=answered,
        total=len(controls),
    )
