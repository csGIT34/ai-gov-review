"""Unit tests for the pure scoring engine and questionnaire template."""
from __future__ import annotations

import pytest

from app.services.questionnaire import get_questionnaire
from app.services.scoring import (
    ScoredControl,
    answer_value,
    score_controls,
    tier_from_score,
)


def _c(key, weight, is_ko, answer, fn="MEASURE", control_id="MEASURE 2.4"):
    return ScoredControl(
        key=key,
        control_id=control_id,
        nist_function=fn,
        weight=weight,
        is_ko=is_ko,
        answer=answer,
    )


# --- answer / weight primitives -------------------------------------------------

def test_answer_values():
    assert answer_value("yes") == 1.0
    assert answer_value("partial") == 0.5
    assert answer_value("no") == 0.0
    assert answer_value("unknown") == 0.0
    # Unanswered is treated as Unknown (risk), never N/A.
    assert answer_value(None) == 0.0


def test_tier_bands():
    assert tier_from_score(0) == 1
    assert tier_from_score(20) == 1
    assert tier_from_score(20.1) == 2
    assert tier_from_score(40) == 2
    assert tier_from_score(41) == 3
    assert tier_from_score(60) == 3
    assert tier_from_score(60.1) == 4
    assert tier_from_score(100) == 4


# --- overall scoring ------------------------------------------------------------

def test_all_yes_is_zero_risk_tier1():
    controls = [_c("a", "high", False, "yes"), _c("b", "low", False, "yes")]
    r = score_controls(controls)
    assert r.overall_score == 0.0
    assert r.tier == 1
    assert r.triggered_gates == []
    assert r.is_complete


def test_all_no_is_max_risk_tier4():
    # Non-KO, non-high so only the score band drives the tier -> 100 -> Tier 4.
    controls = [_c("a", "low", False, "no"), _c("b", "medium", False, "no")]
    r = score_controls(controls)
    assert r.overall_score == 100.0
    assert r.tier == 4


def test_partial_half_credit():
    # Single medium(2) partial(0.5): deficit = 2*0.5 = 1 of 2 -> 50.0
    r = score_controls([_c("a", "medium", False, "partial")])
    assert r.overall_score == 50.0


def test_weighted_average():
    # high(3) yes(0 deficit) + low(1) no(1 deficit) => 1 / 4 = 25.0
    controls = [_c("a", "high", False, "yes"), _c("b", "low", False, "no")]
    r = score_controls(controls)
    assert r.overall_score == 25.0


# --- gate overrides -------------------------------------------------------------

def test_high_weight_no_forces_min_tier3_even_if_score_low():
    # Many yes controls keep the score low, but one high-weight No must floor at Tier 3.
    controls = [_c(f"y{i}", "low", False, "yes") for i in range(10)]
    controls.append(_c("crit", "high", False, "no"))
    r = score_controls(controls)
    assert r.overall_score < 41  # score band alone would be Tier 1/2
    assert r.tier == 3
    assert any(g["type"] == "high_weight_no" for g in r.triggered_gates)


def test_high_weight_unknown_also_triggers_gate():
    controls = [_c(f"y{i}", "low", False, "yes") for i in range(10)]
    controls.append(_c("crit", "high", False, "unknown"))
    r = score_controls(controls)
    assert r.tier >= 3
    assert any(g["type"] == "high_weight_no" for g in r.triggered_gates)


def test_ko_fail_forces_tier4_even_if_score_low():
    controls = [_c(f"y{i}", "low", False, "yes") for i in range(20)]
    controls.append(_c("residency", "high", True, "no"))  # KO
    r = score_controls(controls)
    assert r.overall_score < 61  # band alone would not be Tier 4
    assert r.tier == 4
    assert any(g["type"] == "ko_fail" for g in r.triggered_gates)


def test_ko_unknown_is_a_fail():
    controls = [_c("residency", "high", True, "unknown")]
    r = score_controls(controls)
    assert r.tier == 4
    assert r.triggered_gates[0]["type"] == "ko_fail"


def test_ko_partial_is_not_a_hard_fail():
    # Partial on a KO control contributes deficit but does not force Tier 4 by itself.
    controls = [_c(f"y{i}", "low", False, "yes") for i in range(20)]
    controls.append(_c("residency", "high", True, "partial"))
    r = score_controls(controls)
    assert not any(g["type"] == "ko_fail" for g in r.triggered_gates)
    assert r.tier < 4


def test_ko_takes_precedence_over_high_weight_gate():
    controls = [_c("residency", "high", True, "no")]
    r = score_controls(controls)
    # A KO control that is also high-weight reports as ko_fail (Tier 4), not high_weight_no.
    assert r.tier == 4
    assert r.triggered_gates[0]["type"] == "ko_fail"


# --- function deficits & completeness ------------------------------------------

def test_function_deficits_are_per_function():
    controls = [
        _c("g1", "high", False, "no", fn="GOVERN"),
        _c("m1", "high", False, "yes", fn="MEASURE"),
    ]
    r = score_controls(controls)
    assert r.function_deficits["GOVERN"] == 1.0
    assert r.function_deficits["MEASURE"] == 0.0


def test_incomplete_when_unanswered():
    controls = [_c("a", "low", False, "yes"), _c("b", "low", False, None)]
    r = score_controls(controls)
    assert r.answered == 1
    assert r.total == 2
    assert not r.is_complete


def test_empty_controls_safe():
    r = score_controls([])
    assert r.overall_score == 0.0
    assert r.tier == 1


# --- questionnaire template integrity ------------------------------------------

def test_questionnaire_loads_and_is_valid():
    q = get_questionnaire()
    assert len(q.controls) == 23
    keys = [c.key for c in q.controls]
    assert len(keys) == len(set(keys)), "control keys must be unique"


def test_questionnaire_has_expected_ko_set():
    q = get_questionnaire()
    ko = {c.key for c in q.controls if c.is_ko}
    assert ko == {"model_card", "data_handling", "data_residency", "safety_filters"}


def test_questionnaire_functions_valid():
    q = get_questionnaire()
    for c in q.controls:
        assert c.nist_function in {"GOVERN", "MAP", "MEASURE", "MANAGE"}
        assert c.weight in {"low", "medium", "high"}


def test_scoring_a_full_all_yes_questionnaire():
    q = get_questionnaire()
    controls = [
        ScoredControl(c.key, c.control_id, c.nist_function, c.weight, c.is_ko, "yes")
        for c in q.controls
    ]
    r = score_controls(controls)
    assert r.overall_score == 0.0
    assert r.tier == 1
    assert r.is_complete


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
