from app.rca.llm.schemas import EvidenceObservation, RCAReportDraft
from app.rca.llm.validator import validate_rca_report


def test_rejects_missing_evidence_path():
    evidence = {
        "deployment": {
            "status": "COLLECTED",
        }
    }

    report = RCAReportDraft(
        probable_root_cause="The database CPU was exhausted.",
        root_cause_category="INFRASTRUCTURE",
        confidence="HIGH",
        supporting_observations=[
            EvidenceObservation(
                summary="Database CPU was high.",
                evidence_path="database.cpu_utilization",
            )
        ],
        model="test-model",
        prompt_version="rca-prompt-v1",
    )

    result = validate_rca_report(report=report, evidence_json=evidence)

    assert result["validation_status"] == "FAILED"
    assert "database.cpu_utilization" in result["errors"][0]


def test_high_confidence_is_capped_without_multiple_sources():
    evidence = {
        "metrics": {
            "status": "COLLECTED",
            "error_rate_after": 0.25,
        }
    }

    report = RCAReportDraft(
        probable_root_cause="Error rate increased after the incident started.",
        root_cause_category="APPLICATION_ERROR",
        confidence="HIGH",
        supporting_observations=[
            EvidenceObservation(
                summary="Error rate increased.",
                evidence_path="metrics.error_rate_after",
            )
        ],
        model="test-model",
        prompt_version="rca-prompt-v1",
    )

    result = validate_rca_report(report=report, evidence_json=evidence)

    assert result["validation_status"] == "PASSED"
    assert result["report"].confidence == "MEDIUM"


def test_no_supporting_observations_caps_to_low():
    evidence = {
        "incident": {
            "status": "COLLECTED",
        }
    }

    report = RCAReportDraft(
        probable_root_cause="Insufficient evidence to determine a reliable root cause.",
        root_cause_category="INSUFFICIENT_EVIDENCE",
        confidence="HIGH",
        supporting_observations=[],
        model="test-model",
        prompt_version="rca-prompt-v1",
    )

    result = validate_rca_report(report=report, evidence_json=evidence)

    assert result["validation_status"] == "PASSED"
    assert result["report"].confidence == "LOW"