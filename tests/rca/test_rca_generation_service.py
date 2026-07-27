from unittest.mock import patch
from uuid import uuid4

from app.models import Incident, IncidentEvidence, RCAReport
from app.rca.services.rca_generation_service import request_rca_generation


def test_request_rca_generation_creates_pending_records(db_session):
    incident = Incident(
        id=uuid4(),
        incident_number="INC-8I-001",
        title="Payment service failure",
        severity="SEV-2",
        status="DETECTED",
        environment="staging",
    )

    db_session.add(incident)
    db_session.commit()

    with patch("app.rca.services.rca_generation_service.generate_rca_task.delay") as mock_delay:
        result = request_rca_generation(
            db=db_session,
            incident_id=incident.id,
            requested_by=None,
        )

    evidence = db_session.query(IncidentEvidence).first()
    report = db_session.query(RCAReport).first()

    assert result["status"] == "QUEUED"
    assert evidence.status == "PENDING"
    assert report.status == "PENDING"
    assert report.evidence_id == evidence.id
    mock_delay.assert_called_once()


def test_duplicate_active_generation_returns_existing_report(db_session):
    incident = Incident(
        id=uuid4(),
        incident_number="INC-8I-002",
        title="Checkout failure",
        severity="SEV-2",
        status="DETECTED",
        environment="staging",
    )

    evidence = IncidentEvidence(
        id=uuid4(),
        incident_id=incident.id,
        version=1,
        status="PENDING",
        schema_version="v1",
    )

    report = RCAReport(
        id=uuid4(),
        incident_id=incident.id,
        evidence_id=evidence.id,
        version=1,
        status="PENDING",
        prompt_version="rca_v1",
        #model="gpt-4.1-mini",
    )

    db_session.add_all([incident, evidence, report])
    db_session.commit()

    with patch("app.rca.services.rca_generation_service.generate_rca_task.delay") as mock_delay:
        result = request_rca_generation(
            db=db_session,
            incident_id=incident.id,
            requested_by=None,
        )

    assert result["status"] == "ALREADY_RUNNING"
    assert result["report_id"] == str(report.id)
    mock_delay.assert_not_called()


def test_force_generation_creates_new_version(db_session):
    incident = Incident(
        id=uuid4(),
        incident_number="INC-8I-003",
        title="API latency spike",
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
        #model="gpt-4.1-mini",
    )

    db_session.add_all([incident, evidence, report])
    db_session.commit()

    with patch("app.rca.services.rca_generation_service.generate_rca_task.delay"):
        result = request_rca_generation(
            db=db_session,
            incident_id=incident.id,
            requested_by=None,
            force=True,
        )

    reports = db_session.query(RCAReport).order_by(RCAReport.version.asc()).all()

    assert result["status"] == "QUEUED"
    assert result["version"] == 2
    assert len(reports) == 2
    assert reports[0].status == "COMPLETED"
    assert reports[1].status == "PENDING"
