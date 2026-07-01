"""NIST AI RMF 1.0 category statements, for notating each control.

Each questionnaire control maps to a subcategory id (e.g. "GOVERN 6.1"); we
surface the parent category's official statement so a reviewer sees what the
control means, not just its code.
"""
from __future__ import annotations

CATEGORY_SUMMARIES: dict[str, str] = {
    "GOVERN 1": "Policies, processes, procedures, and practices across the organization related to the mapping, measuring, and managing of AI risks are in place, transparent, and implemented effectively.",
    "GOVERN 2": "Accountability structures are in place so that the appropriate teams and individuals are empowered, responsible, and trained for mapping, measuring, and managing AI risks.",
    "GOVERN 3": "Workforce diversity, equity, inclusion, and accessibility processes are prioritized in the mapping, measuring, and managing of AI risks.",
    "GOVERN 4": "Organizational teams are committed to a culture that considers and communicates AI risk.",
    "GOVERN 5": "Processes are in place for robust engagement with relevant AI actors.",
    "GOVERN 6": "Policies and procedures are in place to address AI risks and benefits arising from third-party software and data and other supply-chain issues.",
    "MAP 1": "Context is established and understood.",
    "MAP 2": "Categorization of the AI system is performed.",
    "MAP 3": "AI capabilities, targeted usage, goals, and expected benefits and costs are understood.",
    "MAP 4": "Risks and benefits are mapped for all components of the AI system, including third-party software and data.",
    "MAP 5": "Impacts to individuals, groups, communities, organizations, and society are characterized.",
    "MEASURE 1": "Appropriate methods and metrics are identified and applied.",
    "MEASURE 2": "AI systems are evaluated for trustworthy characteristics.",
    "MEASURE 3": "Mechanisms for tracking identified AI risks over time are in place.",
    "MEASURE 4": "Feedback about the efficacy of measurement is gathered and assessed.",
    "MANAGE 1": "AI risks based on assessments and other analytical output are prioritized, responded to, and managed.",
    "MANAGE 2": "Strategies to maximize AI benefits and minimize negative impacts are planned, prepared, implemented, documented, and informed by input from relevant AI actors.",
    "MANAGE 3": "AI risks and benefits from third-party entities are managed.",
    "MANAGE 4": "Risk treatments, including response and recovery and communication plans for the identified and measured AI risks, are documented and monitored.",
}


def category_of(control_id: str) -> str:
    """'GOVERN 6.1' -> 'GOVERN 6'."""
    parts = control_id.split()
    if len(parts) != 2:
        return control_id
    return f"{parts[0]} {parts[1].split('.')[0]}"


def control_title(control_id: str) -> str | None:
    """A human notation for a control, e.g. 'GOVERN 6 — Policies ... supply chain.'"""
    summary = CATEGORY_SUMMARIES.get(category_of(control_id))
    return f"{category_of(control_id)} — {summary}" if summary else None
