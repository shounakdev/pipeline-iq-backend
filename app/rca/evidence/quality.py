EVIDENCE_WEIGHTS = {
    "deployment": 0.15,
    "pipeline": 0.10,
    "metrics": 0.20,
    "logs": 0.20,
    "traces": 0.15,
    "kubernetes": 0.10,
    "slo": 0.10,
}


def is_usable_source(source: dict | None) -> bool:
    if not source:
        return False

    status = source.get("status")

    if status in {"COLLECTED", "COMPLETED", "PARTIAL"}:
        return True

    return False


def calculate_completeness_score(evidence: dict) -> float:
    score = 0.0

    for source_name, weight in EVIDENCE_WEIGHTS.items():
        if is_usable_source(evidence.get(source_name)):
            score += weight

    return round(score, 2)


def determine_evidence_status(evidence: dict) -> str:
    incident = evidence.get("incident", {})

    if incident.get("status") == "NO_DATA":
        return "FAILED"

    usable_sources = [
        source_name
        for source_name in EVIDENCE_WEIGHTS
        if is_usable_source(evidence.get(source_name))
    ]

    if not usable_sources:
        return "FAILED"

    if len(usable_sources) == len(EVIDENCE_WEIGHTS):
        return "COMPLETED"

    return "PARTIAL"


def build_missing_sources(evidence: dict) -> list[dict]:
    missing = []

    for source_name in EVIDENCE_WEIGHTS:
        source = evidence.get(source_name)

        if is_usable_source(source):
            continue

        missing.append(
            {
                "source": source_name,
                "status": source.get("status") if isinstance(source, dict) else "NO_DATA",
                "reason": source.get("reason") if isinstance(source, dict) else "Source not collected",
            }
        )

    return missing