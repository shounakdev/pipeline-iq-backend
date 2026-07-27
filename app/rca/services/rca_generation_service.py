from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import Incident, IncidentEvidence, RCAReport
from app.rca.tasks.rca_generation_task import generate_rca_task


ACTIVE_REPORT_STATUSES = {"PENDING", "GENERATING"}
ACTIVE_EVIDENCE_STATUSES = {"PENDING", "COLLECTING"}


class RCAGenerationAlreadyActiveError(Exception):
    pass


class RCAGenerationQueueUnavailableError(Exception):
    pass


class RCAGenerationError(Exception):
    pass


def request_rca_generation(
    db: Session,
    incident_id,
    requested_by=None,
    force: bool = False,
    force_regenerate: bool = False,
    prompt_version: str = "rca_v1",
    model: str = "gpt-4.1-mini",
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if not incident:
        raise RCAGenerationError("Incident not found")

    should_force = force or force_regenerate

    if not should_force:
        active_report = (
            db.query(RCAReport)
            .filter(
                RCAReport.incident_id == incident_id,
                RCAReport.status.in_(ACTIVE_REPORT_STATUSES),
            )
            .order_by(RCAReport.created_at.desc())
            .first()
        )

        if active_report:
            return {
                "status": "ALREADY_RUNNING",
                "incident_id": str(incident_id),
                "report_id": str(active_report.id),
                "report_status": active_report.status,
            }

    latest_version = (
        db.query(RCAReport.version)
        .filter(RCAReport.incident_id == incident_id)
        .order_by(RCAReport.version.desc())
        .first()
    )

    next_version = 1 if not latest_version else latest_version[0] + 1

    evidence = IncidentEvidence(
        id=uuid4(),
        incident_id=incident_id,
        version=next_version,
        status="PENDING",
        schema_version="v1",
    )

    report = RCAReport(
        id=uuid4(),
        incident_id=incident_id,
        evidence_id=evidence.id,
        version=next_version,
        status="PENDING",
        prompt_version=prompt_version,
    )

    try:
        db.add(evidence)
        db.add(report)
        db.commit()
        db.refresh(evidence)
        db.refresh(report)
    except Exception:
        db.rollback()
        raise

    try:
        generate_rca_task.delay(
            incident_id=str(incident_id),
            evidence_id=str(evidence.id),
            report_id=str(report.id),
            prompt_version=prompt_version,
            model=model,
        )
    except Exception as queue_error:
        report.status = "FAILED"
        evidence.status = "FAILED"
        db.commit()

        raise RCAGenerationQueueUnavailableError(
            "RCA generation could not be queued"
        ) from queue_error

    return {
        "status": "QUEUED",
        "incident_id": str(incident_id),
        "evidence_id": str(evidence.id),
        "report_id": str(report.id),
        "version": next_version,
        "report_status": report.status,
        "evidence_status": evidence.status,
    }