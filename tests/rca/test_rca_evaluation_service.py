from uuid import uuid4

from app.models import Incident, IncidentEvidence, RCAFeedback, RCAReport, User
from app.rca.services.rca_evaluation_service import get_rca_evaluation_summary


def create_user(db_session):
    user = User(
        id=str(uuid4()),
        email=f"rca-evaluator-{uuid4()}@example.com",
        password_hash="test-password",
        full_name="RCA Evaluator",
        is_active=True,
    )

    db_session.add(user)
    db_session.commit()

    return user


def create_report(
    db_session,
    *,
    status="COMPLETED",
    confidence="MEDIUM",
    completeness_score=0.75,
):
    incident = Incident(
        id=uuid4(),
        incident_number=f"INC8I-{str(uuid4())[:8]}",
        title="Evaluation incident",
        severity="SEV-2",
        status="DETECTED",
        environment="staging",
    )

    evidence = IncidentEvidence(
        id=uuid4(),
        incident_id=incident.id,
        version=1,
        status="COMPLETED",
        schema_version="v1",
        evidence_payload={
            "completeness_score": completeness_score,
        },
        source_statuses={},
        collection_errors=[],
    )

    report = RCAReport(
        id=uuid4(),
        incident_id=incident.id,
        evidence_id=evidence.id,
        version=1,
        status=status,
        schema_version="v1",
        prompt_version="rca_v1",
        confidence=confidence,
    )

    db_session.add_all([incident, evidence, report])
    db_session.commit()

    return report


def test_rca_evaluation_summary_counts_reports_and_feedback(db_session):
    user = create_user(db_session)

    correct_report = create_report(
        db_session,
        status="COMPLETED",
        confidence="HIGH",
        completeness_score=0.90,
    )

    partial_report = create_report(
        db_session,
        status="COMPLETED",
        confidence="MEDIUM",
        completeness_score=0.70,
    )

    create_report(
        db_session,
        status="FAILED",
        confidence="LOW",
        completeness_score=0.40,
    )

    db_session.add_all(
        [
            RCAFeedback(
                id=uuid4(),
                incident_id=correct_report.incident_id,
                report_id=correct_report.id,
                reviewer_id=user.id,
                rating="CORRECT",
                comment="Correct RCA.",
            ),
            RCAFeedback(
                id=uuid4(),
                incident_id=partial_report.incident_id,
                report_id=partial_report.id,
                reviewer_id=user.id,
                rating="PARTIALLY_CORRECT",
                comment="Partly correct RCA.",
            ),
        ]
    )
    db_session.commit()

    summary = get_rca_evaluation_summary(db_session)

    assert summary["reports_generated"] == 2
    assert summary["reports_failed"] == 1
    assert summary["correct_rating_count"] == 1
    assert summary["partially_correct_rating_count"] == 1
    assert summary["incorrect_rating_count"] == 0
    assert summary["feedback_count"] == 2
    assert summary["feedback_rate"] == 1
    assert summary["average_generation_duration_ms"] == 0
    assert round(summary["average_completeness_score"], 2) == 0.67