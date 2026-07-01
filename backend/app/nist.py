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


# Maintained registry of known NIST AI RMF releases. UPDATE THIS when NIST ships a
# new version (e.g. an AI RMF 2.0 or a revised GenAI Profile): add an entry with a
# later `published` date. The "Check for updates" button compares the version the
# questionnaire implements against the latest entry here — no live scraping, because
# NIST publishes no machine-readable version feed.
KNOWN_RELEASES: list[dict] = [
    {
        "version": "1.0",
        "label": "AI RMF 1.0 + Generative AI Profile",
        "published": "2024-07-26",
        "url": "https://www.nist.gov/itl/ai-risk-management-framework",
        "notes": "AI RMF Core (NIST AI 100-1, Jan 2023) + Generative AI Profile "
        "(NIST AI 600-1, Jul 2024).",
    },
]


def latest_release() -> dict:
    """The newest known NIST AI RMF release (by publication date)."""
    return max(KNOWN_RELEASES, key=lambda r: r["published"])


# Verbatim NIST AI RMF 1.0 subcategory statements (the exact control text) for the
# subcategories used by the questionnaire. Source: AI RMF Core (NIST AI 100-1) /
# airc.nist.gov 5-sec-core.
SUBCATEGORY_TEXT: dict[str, str] = {
    "GOVERN 1.1": "Legal and regulatory requirements involving AI are understood, managed, and documented.",
    "GOVERN 1.5": "Ongoing monitoring and periodic review of the risk management process and its outcomes are planned, and organizational roles and responsibilities are clearly defined, including determining the frequency of periodic review.",
    "GOVERN 4.1": "Organizational policies and practices are in place to foster a critical thinking and safety-first mindset in the design, development, deployment, and uses of AI systems to minimize negative impacts.",
    "GOVERN 6.1": "Policies and procedures are in place that address AI risks associated with third-party entities, including risks of infringement of a third party's intellectual property or other rights.",
    "MAP 1.1": "Intended purposes, potentially beneficial uses, context-specific laws, norms and expectations, and prospective settings in which the AI system will be deployed are understood and documented.",
    "MAP 2.1": "The specific tasks and methods used to implement the tasks that the AI system will support are defined (e.g., classifiers, generative models, recommenders).",
    "MAP 4.1": "Approaches for mapping AI technology and legal risks of its components – including the use of third-party data or software – are in place, followed, and documented.",
    "MAP 4.2": "Internal risk controls for components of the AI system, including third-party AI technologies, are identified and documented.",
    "MAP 5.1": "Likelihood and magnitude of each identified impact (both potentially beneficial and harmful) based on expected use, past uses of AI systems in similar contexts, public incident reports, feedback, or other data are identified and documented.",
    "MEASURE 2.3": "AI system performance or assurance criteria are measured qualitatively or quantitatively and demonstrated for conditions similar to deployment setting(s).",
    "MEASURE 2.4": "The functionality and behavior of the AI system and its components – as identified in the MAP function – are monitored when in production.",
    "MEASURE 2.6": "AI system is evaluated regularly for safety risks – as identified in the MAP function. The AI system to be deployed is demonstrated to be safe, its residual negative risk does not exceed the risk tolerance, and it can fail safely.",
    "MEASURE 2.7": "AI system security and resilience – as identified in the MAP function – are evaluated and documented.",
    "MEASURE 2.9": "The AI model is explained, validated, and documented, and AI system output is interpreted within its context – as identified in the MAP function – to inform responsible use and governance.",
    "MEASURE 2.10": "Privacy risk of the AI system – as identified in the MAP function – is examined and documented.",
    "MEASURE 2.11": "Fairness and bias – as identified in the MAP function – are evaluated and results are documented.",
    "MEASURE 2.12": "Environmental impact and sustainability of AI model training and management activities – as identified in the MAP function – are assessed and documented.",
    "MEASURE 3.1": "Approaches, personnel, and documentation are in place to regularly identify and track existing, unanticipated, and emergent AI risks based on factors such as intended and actual performance.",
    "MANAGE 2.3": "Procedures are followed to respond to and recover from a previously unknown risk when it is identified.",
    "MANAGE 3.1": "AI risks and benefits from third-party resources are regularly monitored, and risk controls are applied and documented.",
    "MANAGE 4.1": "Post-deployment AI system monitoring plans are implemented, including mechanisms for capturing and evaluating input from users and other relevant AI actors, appeal and override, decommissioning, incident response, recovery, and change management.",
}

# NIST AI RMF Playbook (per-function suggested actions). No reliable per-subcategory
# anchors exist, so we link at the function level.
PLAYBOOK_URLS: dict[str, str] = {
    "GOVERN": "https://airc.nist.gov/airmf-resources/playbook/govern/",
    "MAP": "https://airc.nist.gov/airmf-resources/playbook/map/",
    "MEASURE": "https://airc.nist.gov/airmf-resources/playbook/measure/",
    "MANAGE": "https://airc.nist.gov/airmf-resources/playbook/manage/",
}


def category_of(control_id: str) -> str:
    """'GOVERN 6.1' -> 'GOVERN 6'."""
    parts = control_id.split()
    if len(parts) != 2:
        return control_id
    return f"{parts[0]} {parts[1].split('.')[0]}"


def function_of(control_id: str) -> str:
    return control_id.split()[0] if control_id else ""


def control_title(control_id: str) -> str | None:
    """The exact NIST subcategory statement, e.g. 'GOVERN 6.1 — Policies ...'.

    Falls back to the parent category summary if the subcategory text is unknown.
    """
    text = SUBCATEGORY_TEXT.get(control_id)
    if text:
        return f"{control_id} — {text}"
    summary = CATEGORY_SUMMARIES.get(category_of(control_id))
    return f"{category_of(control_id)} — {summary}" if summary else None


def control_url(control_id: str) -> str | None:
    """The NIST Playbook URL for this control's function."""
    return PLAYBOOK_URLS.get(function_of(control_id))
