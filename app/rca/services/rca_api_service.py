from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Incident, IncidentEvidence, RCAFeedback, RCAReport


ACTIVE_REPORT_STATUSES = {"PENDING", "GENERATING"}


class RCAAPINotFoundError(Exception):
    pass


class RCAAPIConflictError(Exception):
    pass


def _status_value(value) -> str:
    return getattr(value, "value", value)


def ensure_incident_exists(db: Session, incident_id: UUID) -> Incident:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise RCAAPINotFoundError("Incident not found")
    return incident


def get_latest_evidence(
    db: Session,
    incident_id: UUID,
    version: int | None = None,
) -> IncidentEvidence:
    ensure_incident_exists(db, incident_id)

    query = db.query(IncidentEvidence).filter(IncidentEvidence.incident_id == incident_id)

    if version is not None:
        query = query.filter(IncidentEvidence.version == version)
    else:
        query = query.order_by(IncidentEvidence.version.desc(), IncidentEvidence.created_at.desc())

    evidence = query.first()
    if not evidence:
        raise RCAAPINotFoundError("Evidence not found")

    return evidence


def get_latest_report(db: Session, incident_id: UUID) -> RCAReport:
    ensure_incident_exists(db, incident_id)

    report = (
        db.query(RCAReport)
        .filter(RCAReport.incident_id == incident_id)
        .order_by(RCAReport.version.desc(), RCAReport.created_at.desc())
        .first()
    )

    if not report:
        raise RCAAPINotFoundError("RCA report not found")

    return report


def create_feedback(
    db: Session,
    incident_id: UUID,
    report_id: UUID,
    rating,
    comment: str | None,
    submitted_by: str | None,
) -> RCAFeedback:
    ensure_incident_exists(db, incident_id)

    report = (
        db.query(RCAReport)
        .filter(RCAReport.id == report_id)
        .first()
    )

    if not report:
        raise RCAAPINotFoundError("RCA report not found")

    if report.incident_id != incident_id:
        raise RCAAPIConflictError("RCA report does not belong to this incident")

    feedback = RCAFeedback(
        incident_id=incident_id,
        report_id=report.id,
        rating=rating,
        comment=comment,
        reviewer_id=submitted_by,
    )

    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    return feedback