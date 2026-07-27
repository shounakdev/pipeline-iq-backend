from app.rca.evidence.bundle import build_evidence_bundle
from app.rca.evidence.hash import generate_evidence_hash
from app.rca.evidence.quality import calculate_completeness_score, determine_evidence_status


def test_completeness_score_is_deterministic():
    evidence = {
        "deployment": {"status": "COLLECTED"},
        "pipeline": {"status": "NO_DATA"},
        "metrics": {"status": "COLLECTED"},
        "logs": {"status": "COLLECTED"},
        "traces": {"status": "NO_DATA"},
        "kubernetes": {"status": "NO_DATA"},
        "slo": {"status": "COLLECTED"},
    }

    assert calculate_completeness_score(evidence) == 0.65


def test_status_failed_when_incident_missing():
    evidence = {
        "incident": {"status": "NO_DATA"},
        "deployment": {"status": "NO_DATA"},
    }

    assert determine_evidence_status(evidence) == "FAILED"


def test_hash_ignores_non_deterministic_fields():
    bundle_a = {
        "incident": {"id": "INC-001"},
        "deployment": {"version": "v1"},
        "collected_at": "2026-07-26T10:00:00",
    }

    bundle_b = {
        "deployment": {"version": "v1"},
        "incident": {"id": "INC-001"},
        "collected_at": "2026-07-26T11:00:00",
    }

    assert generate_evidence_hash(bundle_a) == generate_evidence_hash(bundle_b)


def test_bundle_includes_contradictory_facts():
    raw = {
        "incident": {"status": "COLLECTED"},
        "deployment": {"status": "COLLECTED", "minutes_before_failure": 2},
        "pipeline": {"status": "COLLECTED", "quality_gate": "PASSED"},
        "metrics": {
            "status": "COLLECTED",
            "error_rate_before": 1,
            "error_rate_after": 10,
            "cpu_before": 40,
            "cpu_after": 42,
        },
        "logs": {"status": "NO_DATA"},
        "traces": {"status": "NO_DATA"},
        "kubernetes": {
            "status": "COLLECTED",
            "pod_restart_count": 0,
            "failed_readiness_probe_count": 0,
        },
        "slo": {"status": "NO_DATA"},
    }

    bundle = build_evidence_bundle(raw)

    fact_types = {fact["fact_type"] for fact in bundle["correlation_facts"]}

    assert "NO_POD_HEALTH_DEGRADATION" in fact_types
    assert "QUALITY_GATE_PASSED_DESPITE_RUNTIME_REGRESSION" in fact_types
    assert bundle["evidence_hash"]