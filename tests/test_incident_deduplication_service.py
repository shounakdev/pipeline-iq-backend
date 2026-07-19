"""Service tests for Sprint 7E incident deduplication and escalation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.incidents.service import create_or_update_incident_from_alert
from app.models import (
    AuditEvent,
    Incident,
    IncidentAlertLink,
    IncidentMetric,
    IncidentSeverity,
    IncidentTimelineEvent,
    Project,
    ReliabilityAlert,
    ReliabilityAlertStatus,
    ReliabilityAlertType,
    ReliabilitySeverity,
    Service,
    SLODefinition,
    SLOMetricType,
)


def _create_service_and_slo(
    db: Session,
) -> tuple[Service, SLODefinition]:
    project = Project(
        id=str(uuid4()),
        name="Sprint 7E Service Test Project",
    )
    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name="checkout-api",
        service_type="backend",
        owner="platform-team",
    )
    slo = SLODefinition(
        id=str(uuid4()),
        service_id=service.id,
        metric_type=SLOMetricType.AVAILABILITY,
        target_value=99.9,
        window_minutes=60,
        severity_on_breach=ReliabilitySeverity.HIGH,
        enabled=True,
    )

    db.add_all([project, service, slo])
    db.flush()

    return service, slo


def _create_alert(
    db: Session,
    *,
    service: Service,
    slo: SLODefinition,
    alert_type: ReliabilityAlertType,
    severity: ReliabilitySeverity,
    triggered_value: float,
    threshold_value: float,
    created_at: datetime,
) -> ReliabilityAlert:
    alert = ReliabilityAlert(
        id=str(uuid4()),
        service_id=service.id,
        slo_definition_id=slo.id,
        alert_type=alert_type,
        severity=severity,
        triggered_value=triggered_value,
        threshold_value=threshold_value,
        status=ReliabilityAlertStatus.OPEN,
        created_at=created_at,
    )

    db.add(alert)
    db.flush()
    db.refresh(alert)

    return alert


def _table_count(db: Session, model: type) -> int:
    return db.execute(
        select(func.count()).select_from(model),
    ).scalar_one()


def test_duplicate_alerts_update_one_incident_and_escalate(
    db_session: Session,
) -> None:
    service, slo = _create_service_and_slo(db_session)
    base_time = datetime.now(timezone.utc) - timedelta(hours=2)

    medium_alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        alert_type=ReliabilityAlertType.SLO_BREACH,
        severity=ReliabilitySeverity.MEDIUM,
        triggered_value=99.7,
        threshold_value=99.9,
        created_at=base_time,
    )

    first_result = create_or_update_incident_from_alert(
        db_session,
        medium_alert,
        environment="production",
    )
    incident_id = first_result.incident.incident_id

    first_incident = db_session.get(Incident, incident_id)

    assert first_incident is not None
    assert first_incident.severity == IncidentSeverity.SEV_3

    high_alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        alert_type=ReliabilityAlertType.SLO_BREACH,
        severity=ReliabilitySeverity.HIGH,
        triggered_value=99.4,
        threshold_value=99.9,
        created_at=base_time + timedelta(minutes=25),
    )

    second_result = create_or_update_incident_from_alert(
        db_session,
        high_alert,
        environment="production",
    )

    assert second_result.incident.incident_id == incident_id

    db_session.refresh(first_incident)
    assert first_incident.severity == IncidentSeverity.SEV_2

    critical_availability_alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        alert_type=ReliabilityAlertType.AVAILABILITY_BREACH,
        severity=ReliabilitySeverity.HIGH,
        triggered_value=94.0,
        threshold_value=99.9,
        created_at=base_time + timedelta(minutes=50),
    )

    third_result = create_or_update_incident_from_alert(
        db_session,
        critical_availability_alert,
        environment="production",
    )

    assert third_result.incident.incident_id == incident_id

    db_session.refresh(first_incident)
    assert first_incident.severity == IncidentSeverity.SEV_1

    lower_alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        alert_type=ReliabilityAlertType.SLO_BREACH,
        severity=ReliabilitySeverity.LOW,
        triggered_value=99.8,
        threshold_value=99.9,
        created_at=base_time + timedelta(minutes=55),
    )

    fourth_result = create_or_update_incident_from_alert(
        db_session,
        lower_alert,
        environment="production",
    )

    assert fourth_result.incident.incident_id == incident_id

    db_session.refresh(first_incident)

    # Open incidents never decrease severity automatically.
    assert first_incident.severity == IncidentSeverity.SEV_1

    assert _table_count(db_session, Incident) == 1
    assert _table_count(db_session, IncidentAlertLink) == 4
    assert _table_count(db_session, IncidentMetric) == 8

    severity_events = list(
        db_session.execute(
            select(IncidentTimelineEvent)
            .where(
                IncidentTimelineEvent.incident_id == incident_id,
                IncidentTimelineEvent.event_type == "SEVERITY_CHANGED",
            )
            .order_by(IncidentTimelineEvent.occurred_at),
        ).scalars()
    )

    assert len(severity_events) == 2

    assert severity_events[0].metadata_json["previous_severity"] == "SEV-3"
    assert severity_events[0].metadata_json["new_severity"] == "SEV-2"
    assert severity_events[0].metadata_json["reason_code"]
    assert severity_events[0].metadata_json["explanation"]
    assert severity_events[0].metadata_json["evidence"]

    assert severity_events[1].metadata_json["previous_severity"] == "SEV-2"
    assert severity_events[1].metadata_json["new_severity"] == "SEV-1"
    assert (
        severity_events[1].metadata_json["reason_code"]
        == "CRITICAL_AVAILABILITY"
    )

    severity_audits = list(
        db_session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.entity_id == str(incident_id),
                AuditEvent.action == "INCIDENT_SEVERITY_CHANGED",
            )
            .order_by(AuditEvent.created_at),
        ).scalars()
    )

    assert len(severity_audits) == 2

    first_audit_details = json.loads(severity_audits[0].details)
    second_audit_details = json.loads(severity_audits[1].details)

    assert first_audit_details["previous_severity"] == "SEV-3"
    assert first_audit_details["new_severity"] == "SEV-2"
    assert second_audit_details["previous_severity"] == "SEV-2"
    assert second_audit_details["new_severity"] == "SEV-1"
    assert second_audit_details["reason_code"] == "CRITICAL_AVAILABILITY"

    counts_before_reprocessing = {
        "incidents": _table_count(db_session, Incident),
        "links": _table_count(db_session, IncidentAlertLink),
        "metrics": _table_count(db_session, IncidentMetric),
        "timeline": _table_count(db_session, IncidentTimelineEvent),
        "audits": _table_count(db_session, AuditEvent),
    }

    repeated_result = create_or_update_incident_from_alert(
        db_session,
        lower_alert,
        environment="production",
    )

    assert repeated_result.incident.incident_id == incident_id

    counts_after_reprocessing = {
        "incidents": _table_count(db_session, Incident),
        "links": _table_count(db_session, IncidentAlertLink),
        "metrics": _table_count(db_session, IncidentMetric),
        "timeline": _table_count(db_session, IncidentTimelineEvent),
        "audits": _table_count(db_session, AuditEvent),
    }

    # Reprocessing the same alert must not create duplicate records.
    assert counts_after_reprocessing == counts_before_reprocessing


def test_alert_outside_window_creates_new_incident(
    db_session: Session,
) -> None:
    service, slo = _create_service_and_slo(db_session)
    base_time = datetime.now(timezone.utc) - timedelta(hours=2)

    first_alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        alert_type=ReliabilityAlertType.SLO_BREACH,
        severity=ReliabilitySeverity.MEDIUM,
        triggered_value=99.7,
        threshold_value=99.9,
        created_at=base_time,
    )

    first_result = create_or_update_incident_from_alert(
        db_session,
        first_alert,
        environment="production",
    )

    later_alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        alert_type=ReliabilityAlertType.SLO_BREACH,
        severity=ReliabilitySeverity.MEDIUM,
        triggered_value=99.6,
        threshold_value=99.9,
        created_at=base_time + timedelta(minutes=31),
    )

    second_result = create_or_update_incident_from_alert(
        db_session,
        later_alert,
        environment="production",
    )

    assert (
        second_result.incident.incident_id
        != first_result.incident.incident_id
    )
    assert _table_count(db_session, Incident) == 2


def test_different_environment_creates_new_incident(
    db_session: Session,
) -> None:
    service, slo = _create_service_and_slo(db_session)
    alert_time = datetime.now(timezone.utc)

    production_alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        alert_type=ReliabilityAlertType.SLO_BREACH,
        severity=ReliabilitySeverity.HIGH,
        triggered_value=99.5,
        threshold_value=99.9,
        created_at=alert_time,
    )

    production_result = create_or_update_incident_from_alert(
        db_session,
        production_alert,
        environment="production",
    )

    staging_alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        alert_type=ReliabilityAlertType.SLO_BREACH,
        severity=ReliabilitySeverity.HIGH,
        triggered_value=99.5,
        threshold_value=99.9,
        created_at=alert_time + timedelta(minutes=1),
    )

    staging_result = create_or_update_incident_from_alert(
        db_session,
        staging_alert,
        environment="staging",
    )

    assert (
        staging_result.incident.incident_id
        != production_result.incident.incident_id
    )
    assert staging_result.incident.severity == IncidentSeverity.SEV_3
    assert _table_count(db_session, Incident) == 2
