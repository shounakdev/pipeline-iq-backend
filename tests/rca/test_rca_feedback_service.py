from uuid import uuid4

from app.models import Incident, IncidentEvidence, RCAFeedback, RCAReport, User
from app.rca.services.rca_feedback_service import submit_rca_feedback


def create_user(db_session):
    user = User(
        id=str(uuid4()),
        email=f"rca-reviewer-{uuid4()}@example.com",
        password_hash="test-password",
        full_name="RCA Reviewer",
        is_active=True,
    )

    db_session.add(user)
    db_session.commit()

    return user


def create_completed_report(db_session):
    incident = Incident(
        id=uuid4(),
        incident_number="INC-8I-FB-001",
        title="Payment service failure",
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
    )

    report = RCAReport(
        id=uuid4(),
        incident_id=incident.id,
        evidence_id=evidence.id,
        version=1,
        status="COMPLETED",
        prompt_version="rca_v1",
    )

    db_session.add_all([incident, evidence, report])
    db_session.commit()

    return report


def test_submit_rca_feedback_creates_rating(db_session):
    report = create_completed_report(db_session)
    user = create_user(db_session)

    feedback = submit_rca_feedback(
        db=db_session,
        report_id=report.id,
        user_id=user.id,
        rating="PARTIALLY_CORRECT",
        comment="Root cause was partly correct.",
    )

    saved = db_session.query(RCAFeedback).first()

    assert feedback.id == saved.id
    assert saved.report_id == report.id
    assert saved.reviewer_id == user.id
    assert saved.rating == "PARTIALLY_CORRECT"
    assert saved.comment == "Root cause was partly correct."


def test_submit_rca_feedback_updates_same_user_rating(db_session):
    report = create_completed_report(db_session)
    user = create_user(db_session)

    submit_rca_feedback(
        db=db_session,
        report_id=report.id,
        user_id=user.id,
        rating="INCORRECT",
        comment="Initial feedback.",
    )

    updated = submit_rca_feedback(
        db=db_session,
        report_id=report.id,
        user_id=user.id,
        rating="CORRECT",
        comment="Updated feedback.",
    )

    all_feedback = db_session.query(RCAFeedback).all()

    assert len(all_feedback) == 1
    assert updated.rating == "CORRECT"
    assert updated.comment == "Updated feedback."
    assert updated.reviewer_id == user.id