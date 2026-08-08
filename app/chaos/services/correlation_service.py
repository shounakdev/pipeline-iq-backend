"""Correlate platform events to the chaos run that could have caused them."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chaos import repository
from app.chaos.services.observation_service import record_observation
from app.events.constants import (
    ALERT_CREATED,
    INCIDENT_CREATED,
    RCA_COMPLETED,
    RECOVERY_FAILED,
    RECOVERY_VERIFIED,
    RELIABILITY_ALERT_CREATED,
    REMEDIATION_APPROVED,
    REMEDIATION_COMPLETED,
    REMEDIATION_RECOMMENDED,
)
from app.models import (
    ChaosObservationType,
    ChaosRun,
    EventRecord,
    Incident,
    RCAReport,
    RecoveryVerification,
    ReliabilityAlert,
    RemediationExecution,
    RemediationRecommendation,
)


CORRELATION_EVENT_TYPES = {
    ALERT_CREATED,
    RELIABILITY_ALERT_CREATED,
    INCIDENT_CREATED,
    RCA_COMPLETED,
    REMEDIATION_RECOMMENDED,
    REMEDIATION_APPROVED,
    REMEDIATION_COMPLETED,
    RECOVERY_VERIFIED,
    RECOVERY_FAILED,
}


def _payload(record: EventRecord) -> dict[str, Any]:
    return record.payload if isinstance(record.payload, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _event_time(record: EventRecord) -> datetime:
    payload = _payload(record)
    return (
        _parse_time(payload.get("occurred_at"))
        or _parse_time(payload.get("created_at"))
        or _parse_time(record.timestamp)
        or datetime.now(timezone.utc)
    )


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def _find_run(
    db: Session,
    *,
    service_id: str | None,
    environment: str | None,
    occurred_at: datetime,
    incident_id: UUID | None = None,
) -> ChaosRun | None:
    if not service_id or not environment:
        return None
    statement = select(ChaosRun).where(
        ChaosRun.target_service_id == service_id,
        ChaosRun.target_environment == environment,
        ChaosRun.failure_injected_at.is_not(None),
        ChaosRun.failure_injected_at <= occurred_at,
        ChaosRun.deadline_at >= occurred_at,
    )
    if incident_id is not None:
        statement = statement.where(
            (ChaosRun.incident_id.is_(None))
            | (ChaosRun.incident_id == incident_id)
        )
    return db.scalars(
        statement.order_by(
            ChaosRun.failure_injected_at.desc(),
            ChaosRun.id.asc(),
        ).limit(1)
    ).first()


def correlate_event(db: Session, record: EventRecord) -> ChaosRun | None:
    """Link a supported platform event and append its timeline observation."""
    if record.event_type not in CORRELATION_EVENT_TYPES:
        return None

    payload = _payload(record)
    occurred_at = _event_time(record)
    service_id = record.service_id or payload.get("service_id")
    environment = record.environment or payload.get("environment")
    incident_id = _uuid(payload.get("incident_id"))
    resource: Any = None
    observation_type: ChaosObservationType
    singleton = False

    if record.event_type in {ALERT_CREATED, RELIABILITY_ALERT_CREATED}:
        resource_id = payload.get("reliability_alert_id") or payload.get("alert_id")
        resource = db.get(ReliabilityAlert, str(resource_id)) if resource_id else None
        if resource is not None:
            service_id = resource.service_id
            occurred_at = resource.created_at or occurred_at
        observation_type = ChaosObservationType.ALERT_CREATED
        singleton = True
    elif record.event_type == INCIDENT_CREATED:
        resource = db.get(Incident, incident_id) if incident_id else None
        if resource is not None:
            service_id = resource.primary_service_id
            environment = resource.environment
            occurred_at = resource.detected_at or resource.created_at or occurred_at
            incident_id = resource.id
        observation_type = ChaosObservationType.INCIDENT_CREATED
        singleton = True
    elif record.event_type == RCA_COMPLETED:
        report_id = _uuid(payload.get("rca_report_id") or payload.get("report_id"))
        resource = db.get(RCAReport, report_id) if report_id else None
        if resource is not None:
            incident_id = resource.incident_id
            occurred_at = resource.generated_at or resource.updated_at or occurred_at
        observation_type = ChaosObservationType.RCA_COMPLETED
    elif record.event_type in {REMEDIATION_RECOMMENDED, REMEDIATION_APPROVED}:
        recommendation_id = _uuid(payload.get("recommendation_id"))
        resource = (
            db.get(RemediationRecommendation, recommendation_id)
            if recommendation_id
            else None
        )
        if resource is not None:
            incident_id = resource.incident_id
            service_id = resource.service_id
            environment = resource.environment
            occurred_at = (
                _parse_time(payload.get("occurred_at"))
                or resource.created_at
                or occurred_at
            )
        observation_type = (
            ChaosObservationType.REMEDIATION_APPROVED
            if record.event_type == REMEDIATION_APPROVED
            else ChaosObservationType.REMEDIATION_RECOMMENDED
        )
    elif record.event_type == REMEDIATION_COMPLETED:
        execution_id = _uuid(payload.get("execution_id"))
        resource = db.get(RemediationExecution, execution_id) if execution_id else None
        if resource is not None:
            recommendation = resource.remediation
            incident_id = recommendation.incident_id
            service_id = recommendation.service_id
            environment = recommendation.environment
            occurred_at = resource.completed_at or resource.created_at or occurred_at
        observation_type = ChaosObservationType.REMEDIATION_EXECUTED
    else:
        verification_id = _uuid(payload.get("verification_id"))
        resource = db.get(RecoveryVerification, verification_id) if verification_id else None
        if resource is not None:
            recommendation = resource.remediation
            incident_id = recommendation.incident_id
            service_id = recommendation.service_id
            environment = recommendation.environment
            occurred_at = resource.verified_at or resource.created_at or occurred_at
        observation_type = ChaosObservationType.RECOVERY_COMPLETED

    if incident_id is not None:
        incident = db.get(Incident, incident_id)
        if incident is None:
            return None
        service_id = incident.primary_service_id or service_id
        environment = incident.environment or environment

    run = _find_run(
        db,
        service_id=str(service_id) if service_id else None,
        environment=str(environment) if environment else None,
        occurred_at=occurred_at,
        incident_id=incident_id,
    )
    if run is None:
        return None

    link_values: dict[str, UUID] = {}
    if incident_id is not None:
        link_values["incident_id"] = incident_id
    if isinstance(resource, RCAReport):
        link_values["rca_report_id"] = resource.id
    elif isinstance(resource, RemediationRecommendation):
        link_values["remediation_id"] = resource.id
    elif isinstance(resource, RemediationExecution):
        link_values["remediation_id"] = resource.remediation_id
        link_values["remediation_execution_id"] = resource.id
    elif isinstance(resource, RecoveryVerification):
        link_values["remediation_id"] = resource.remediation_id
        link_values["remediation_execution_id"] = resource.remediation_execution_id
        link_values["recovery_verification_id"] = resource.id
    if link_values:
        repository.link_run_artifacts(db, chaos_run=run, **link_values)

    resource_id = (
        getattr(resource, "id", None)
        or payload.get("resource_id")
        or payload.get("reliability_alert_id")
        or payload.get("alert_id")
        or payload.get("approval_id")
        or record.event_id
    )
    details = dict(payload)
    details["event_type"] = record.event_type
    details["event_id"] = record.event_id
    if record.event_type in {RECOVERY_VERIFIED, RECOVERY_FAILED}:
        details["recovery_succeeded"] = record.event_type == RECOVERY_VERIFIED
    record_observation(
        db,
        run=run,
        observation_type=observation_type,
        observed_at=occurred_at,
        source="platformiq-event",
        resource_type=type(resource).__name__ if resource is not None else record.event_type,
        resource_id=str(resource_id),
        details=details,
        singleton=singleton,
    )
    return run