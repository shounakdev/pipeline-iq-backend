from datetime import datetime, timezone
from types import SimpleNamespace

from app.rca.collectors.deployment_collector import collect_deployment_evidence
from app.rca.collectors.derived_facts import build_derived_facts
from app.rca.collectors.evidence_collector import collect_native_evidence
from app.rca.collectors.pipeline_collector import collect_pipeline_evidence


class QueryStub:
    def __init__(self, first_result=None, all_result=None):
        self.first_result = first_result
        self.all_result = all_result or []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.first_result

    def all(self):
        return self.all_result


class DbStub:
    def __init__(self, first_result=None):
        self.first_result = first_result

    def query(self, *args, **kwargs):
        return QueryStub(first_result=self.first_result)


def test_deployment_collector_returns_no_data_when_no_deployment_found():
    db = DbStub(first_result=None)

    incident = {
        "primary_service_id": "service-1",
        "environment": "staging",
        "failure_started_at": datetime(2026, 7, 25, 10, 5, tzinfo=timezone.utc),
        "suspected_deployment_id": None,
    }

    result = collect_deployment_evidence(db, incident)

    assert result["status"] == "NO_DATA"
    assert result["correlation_method"] == "NO_DATA"
    assert "No deployment found" in result["reason"]


def test_pipeline_collector_normalizes_pipeline_run_fields():
    pipeline_run = SimpleNamespace(
        id="pipe-1",
        status="FAILED",
        quality_gate="FAILED",
        test_status="PASSED",
        trivy_status="FAILED",
        risk_score=87.5,
        stage="SECURITY_SCAN",
        trivy_high=3,
        trivy_medium=7,
        finished_at=datetime(2026, 7, 25, 10, 10, tzinfo=timezone.utc),
    )

    db = DbStub(first_result=pipeline_run)

    result = collect_pipeline_evidence(db, "pipe-1")

    assert result["status"] == "COLLECTED"
    assert result["pipeline_run_id"] == "pipe-1"
    assert result["pipeline_status"] == "FAILED"
    assert result["quality_gate"] == "FAILED"
    assert result["test_result"] == "PASSED"
    assert result["security_scan_result"] == "FAILED"
    assert result["release_risk_score"] == 87.5
    assert result["failed_stage"] == "SECURITY_SCAN"
    assert result["high_severity_findings"] == 3
    assert result["medium_severity_findings"] == 7
    assert result["completed_at"] == pipeline_run.finished_at
    assert "not proof" in result["interpretation_note"]


def test_collect_native_evidence_returns_all_native_sections(monkeypatch):
    from app.rca.collectors import evidence_collector

    incident = {
        "status": "COLLECTED",
        "incident_id": "incident-1",
        "failure_started_at": datetime(2026, 7, 25, 10, 5, tzinfo=timezone.utc),
    }

    deployment = {
        "status": "COLLECTED",
        "deployment_id": "deployment-1",
        "pipeline_run_id": "pipe-1",
        "deployed_at": datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
        "minutes_before_failure": 5,
    }

    pipeline = {
        "status": "COLLECTED",
        "pipeline_run_id": "pipe-1",
    }

    slo = {
        "status": "COLLECTED",
        "breach_status": "BREACHED",
        "target": 99.9,
        "measured_value": 99.5,
    }

    monkeypatch.setattr(
        evidence_collector,
        "collect_incident_evidence",
        lambda db, incident_id: incident,
    )
    monkeypatch.setattr(
        evidence_collector,
        "collect_deployment_evidence",
        lambda db, incident: deployment,
    )
    monkeypatch.setattr(
        evidence_collector,
        "collect_pipeline_evidence",
        lambda db, pipeline_run_id: pipeline,
    )
    monkeypatch.setattr(
        evidence_collector,
        "collect_slo_evidence",
        lambda db, incident: slo,
    )

    result = collect_native_evidence(db=object(), incident_id="incident-1")

    assert result["incident"] == incident
    assert result["deployment"] == deployment
    assert result["pipeline"] == pipeline
    assert result["slo"] == slo
    assert result["derived_facts"]
    assert result["derived_facts"][0]["fact_type"] == "DEPLOYMENT_TEMPORAL_CORRELATION"


def test_builds_deployment_temporal_correlation_fact():
    incident = {
        "failure_started_at": datetime(2026, 7, 25, 10, 2, tzinfo=timezone.utc),
    }

    deployment = {
        "status": "COLLECTED",
        "deployed_at": datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
        "minutes_before_failure": 2,
    }

    facts = build_derived_facts(
        incident=incident,
        deployment=deployment,
        slo=None,
    )

    assert len(facts) == 1
    assert facts[0]["fact_type"] == "DEPLOYMENT_TEMPORAL_CORRELATION"
    assert "2 minutes" in facts[0]["description"]


def test_builds_slo_breach_fact():
    incident = {}

    slo = {
        "status": "COLLECTED",
        "target": 99.9,
        "measured_value": 99.5,
        "breach_status": "BREACHED",
    }

    facts = build_derived_facts(
        incident=incident,
        deployment=None,
        slo=slo,
    )

    assert len(facts) == 1
    assert facts[0]["fact_type"] == "SLO_BREACH"


def test_no_deployment_fact_when_deployment_missing():
    incident = {
        "failure_started_at": datetime(2026, 7, 25, 10, 2, tzinfo=timezone.utc),
    }

    facts = build_derived_facts(
        incident=incident,
        deployment={"status": "NO_DATA"},
        slo=None,
    )

    assert facts == []