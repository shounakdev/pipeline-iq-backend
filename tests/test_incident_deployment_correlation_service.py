"""Service integration tests for Sprint 7F deployment correlation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.incidents.service import create_or_update_incident_from_alert
from app.models import (
    AuditEvent,
    Deployment,
    Environment,
    Incident,
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


def _create_service_context(
    db: Session,
) -> tuple[Service, SLODefinition, Environment]:
    project = Project(
        id=str(uuid4()),
        name=f"Sprint 7F Deployment Service Project {uuid4()}",
    )
    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name="payment-service",
        service_type="backend",
        owner="platform-team",
    )
    environment = Environment(
        id=str(uuid4()),
        service_id=service.id,
        name="production",
        is_active=True,
    )
    slo = SLODefinition(
        id=str(uuid4()),
        service_id=service.id,
        metric_type=SLOMetricType.P95_LATENCY,
        target_value=500.0,
        window_minutes=60,
        severity_on_breach=ReliabilitySeverity.HIGH,
        enabled=True,
    )

    db.add_all(
        [
            project,
            service,
            environment,
            slo,
        ]
    )
    db.flush()

    return service, slo, environment


def _create_deployment(
    db: Session,
    *,
    service: Service,
    environment: Environment,
    created_at: datetime,
    version: str,
) -> Deployment:
    deployment = Deployment(
        service_id=service.id,
        environment_id=environment.id,
        service_name=service.name,
        image_tag=f"payment-service:{version}",
        deployment_version=version,
        commit_sha="abc123",
        argo_sync_status="Synced",
        kubernetes_rollout_status="Healthy",
        created_at=created_at,
        deployed_at=created_at,
    )

    db.add(deployment)
    db.flush()

    return deployment


def _create_alert(
    db: Session,
    *,
    service: Service,
    slo: SLODefinition,
    created_at: datetime,
    deployment_id=None,
) -> ReliabilityAlert:
    alert = ReliabilityAlert(
        id=str(uuid4()),
        service_id=service.id,
        slo_definition_id=slo.id,
        alert_type=ReliabilityAlertType.LATENCY_BREACH,
        severity=ReliabilitySeverity.HIGH,
        triggered_value=900.0,
        threshold_value=500.0,
        deployment_id=deployment_id,
        status=ReliabilityAlertStatus.OPEN,
        created_at=created_at,
    )

    db.add(alert)
    db.flush()
    db.refresh(alert)

    return alert


def _event_count(
    db: Session,
    *,
    incident_id,
    event_type: str,
) -> int:
    return db.execute(
        select(func.count())
        .select_from(IncidentTimelineEvent)
        .where(
            IncidentTimelineEvent.incident_id == incident_id,
            IncidentTimelineEvent.event_type == event_type,
        )
    ).scalar_one()


def test_service_stores_suspected_deployment_and_timeline_event(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service, slo, environment = _create_service_context(
        db_session,
    )

    older = _create_deployment(
        db_session,
        service=service,
        environment=environment,
        created_at=detected_at - timedelta(minutes=45),
        version="v1",
    )
    suspected = _create_deployment(
        db_session,
        service=service,
        environment=environment,
        created_at=detected_at - timedelta(minutes=10),
        version="v2",
    )

    # Intentionally point the alert at the older deployment.
    # The incident service must independently select the latest
    # eligible deployment instead of trusting alert.deployment_id.
    alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        created_at=detected_at,
        deployment_id=older.id,
    )

    result = create_or_update_incident_from_alert(
        db_session,
        alert,
        environment="production",
    )
    incident_id = result.incident.incident_id

    incident = db_session.get(
        Incident,
        incident_id,
    )

    assert incident is not None
    assert incident.suspected_deployment_id == suspected.id
    assert incident.suspected_deployment_id != older.id

    assert result.suspected_deployment is not None
    assert result.suspected_deployment.id == suspected.id
    assert result.suspected_deployment.deployment_version == "v2"

    event = db_session.execute(
        select(IncidentTimelineEvent).where(
            IncidentTimelineEvent.incident_id == incident_id,
            IncidentTimelineEvent.event_type
            == "DEPLOYMENT_CORRELATED",
        )
    ).scalar_one()

    assert event.deployment_id == suspected.id
    assert event.source == "DEPLOYMENT_CORRELATION"
    assert "Suspected deployment" in event.message
    assert "latest matching production deployment" in event.message

    message_lower = event.message.lower()

    assert "caused by" not in message_lower
    assert "root cause" not in message_lower
    assert "caused the incident" not in message_lower

    assert event.metadata_json["classification"] == (
        "suspected_deployment"
    )
    assert event.metadata_json["deployment_id"] == str(
        suspected.id
    )
    assert event.metadata_json[
        "correlation_window_minutes"
    ] == 60
    assert isinstance(
        event.metadata_json["deployment_created_at"],
        str,
    )
    assert isinstance(
        event.metadata_json["incident_detected_at"],
        str,
    )

    audit = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(incident_id),
            AuditEvent.action
            == "INCIDENT_DEPLOYMENT_CORRELATED",
        )
    ).scalar_one()

    assert audit is not None

    counts_before = {
        "timeline": _event_count(
            db_session,
            incident_id=incident_id,
            event_type="DEPLOYMENT_CORRELATED",
        ),
        "audits": db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.entity_id == str(incident_id),
                AuditEvent.action
                == "INCIDENT_DEPLOYMENT_CORRELATED",
            )
        ).scalar_one(),
    }

    repeated = create_or_update_incident_from_alert(
        db_session,
        alert,
        environment="production",
    )

    assert repeated.incident.incident_id == incident_id

    counts_after = {
        "timeline": _event_count(
            db_session,
            incident_id=incident_id,
            event_type="DEPLOYMENT_CORRELATED",
        ),
        "audits": db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.entity_id == str(incident_id),
                AuditEvent.action
                == "INCIDENT_DEPLOYMENT_CORRELATED",
            )
        ).scalar_one(),
    }

    assert counts_before == {
        "timeline": 1,
        "audits": 1,
    }
    assert counts_after == counts_before


def test_service_allows_incident_without_matching_deployment(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service, slo, environment = _create_service_context(
        db_session,
    )

    old_deployment = _create_deployment(
        db_session,
        service=service,
        environment=environment,
        created_at=detected_at - timedelta(minutes=61),
        version="old",
    )

    alert = _create_alert(
        db_session,
        service=service,
        slo=slo,
        created_at=detected_at,
        deployment_id=old_deployment.id,
    )

    result = create_or_update_incident_from_alert(
        db_session,
        alert,
        environment="production",
    )
    incident_id = result.incident.incident_id

    incident = db_session.get(
        Incident,
        incident_id,
    )

    assert incident is not None
    assert incident.suspected_deployment_id is None
    assert result.suspected_deployment is None

    assert _event_count(
        db_session,
        incident_id=incident_id,
        event_type="DEPLOYMENT_CORRELATED",
    ) == 0
