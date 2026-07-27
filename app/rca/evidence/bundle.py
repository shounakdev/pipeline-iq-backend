from app.rca.evidence.correlation import build_correlation_facts
from app.rca.evidence.hash import generate_evidence_hash
from app.rca.evidence.quality import (
    build_missing_sources,
    calculate_completeness_score,
    determine_evidence_status,
)


def build_evidence_bundle(raw_evidence: dict) -> dict:
    correlation_facts = build_correlation_facts(raw_evidence)
    completeness_score = calculate_completeness_score(raw_evidence)
    status = determine_evidence_status(raw_evidence)
    missing_sources = build_missing_sources(raw_evidence)

    bundle = {
        "schema_version": "rca-evidence-bundle/v1",
        "status": status,
        "completeness_score": completeness_score,
        "incident": raw_evidence.get("incident"),
        "deployment": raw_evidence.get("deployment"),
        "pipeline": raw_evidence.get("pipeline"),
        "slo": raw_evidence.get("slo"),
        "metrics": raw_evidence.get("metrics"),
        "logs": raw_evidence.get("logs"),
        "traces": raw_evidence.get("traces"),
        "kubernetes": raw_evidence.get("kubernetes"),
        "derived_facts": raw_evidence.get("derived_facts", []),
        "correlation_facts": correlation_facts,
        "missing_sources": missing_sources,
        "collector_errors": raw_evidence.get("collector_errors", []),
    }

    bundle["evidence_hash"] = generate_evidence_hash(bundle)

    return bundle