import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    Incident,
    IncidentEvent,
    IncidentSeverity,
    IncidentStatus,
)

logger = logging.getLogger(__name__)

ACTIVE_INCIDENT_STATUSES = [
    IncidentStatus.OPEN,
    IncidentStatus.ACKNOWLEDGED,
]


def _severity_from_alert(alert_severity: str | None) -> IncidentSeverity:
    if alert_severity == "CRITICAL":
        return IncidentSeverity.CRITICAL
    if alert_severity == "HIGH":
        return IncidentSeverity.HIGH
    if alert_severity == "MEDIUM":
        return IncidentSeverity.MEDIUM
    return IncidentSeverity.LOW


def _build_correlation_id(alert_event: dict[str, Any]) -> str:
    service_id = alert_event.get("service_id")
    environment = alert_event.get("environment", "unknown")
    event_type = alert_event.get("event_type", "UNKNOWN_ALERT")

    return alert_event.get("correlation_id") or f"{service_id}:{environment}:{event_type}"


def _build_title(alert_event: dict[str, Any]) -> str:
    service_name = alert_event.get("service_name") or alert_event.get("service_id")
    environment = alert_event.get("environment", "unknown")
    event_type = alert_event.get("event_type", "UNKNOWN_ALERT")

    readable = event_type.replace("_", " ").title()
    return f"{service_name} {readable.lower()} in {environment}"


def _build_description(alert_event: dict[str, Any]) -> str:
    service_name = alert_event.get("service_name") or alert_event.get("service_id")
    environment = alert_event.get("environment", "unknown")
    event_type = alert_event.get("event_type", "UNKNOWN_ALERT")

    return (
        f"Incident created from telemetry alert {event_type} "
        f"for {service_name} in {environment}."
    )


def _event_to_out(event: IncidentEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "incident_id": event.incident_id,
        "event_type": event.event_type,
        "message": event.message,
        "metadata": event.event_metadata,
        "created_at": event.created_at,
    }


def incident_to_out(incident: Incident) -> dict[str, Any]:
    return {
        "id": incident.id,
        "title": incident.title,
        "description": incident.description,
        "severity": incident.severity.value if hasattr(incident.severity, "value") else incident.severity,
        "status": incident.status.value if hasattr(incident.status, "value") else incident.status,
        "service_id": incident.service_id,
        "environment": incident.environment,
        "correlation_id": incident.correlation_id,
        "triggered_by_event_id": incident.triggered_by_event_id,
        "started_at": incident.started_at,
        "resolved_at": incident.resolved_at,
        "created_at": incident.created_at,
        "updated_at": incident.updated_at,
    }


def incident_detail_to_out(incident: Incident) -> dict[str, Any]:
    data = incident_to_out(incident)
    data["events"] = [_event_to_out(event) for event in incident.events]
    return data


def publish_incident_event(event_type: str, payload: dict[str, Any]) -> None:
    """
    Replace the body of this function with your existing Sprint 4/5 Kafka publisher.

    Topic:
        incident.events
    """
    try:
        # Example if you already have a publisher:
        # from app.events.publisher import publish_event
        # publish_event(topic="incident.events", event_type=event_type, payload=payload)
        logger.info("Incident event emitted: %s payload=%s", event_type, payload)
    except Exception:
        logger.exception("Failed to publish incident event")


def create_or_update_incident_from_alert(
    db: Session,
    alert_event: dict[str, Any],
) -> Incident:
    """
    Converts a telemetry alert into an incident.

    If an active incident already exists for the same service/environment/alert type,
    we attach another incident event instead of creating duplicate incidents.
    """

    correlation_id = _build_correlation_id(alert_event)

    incident = (
        db.query(Incident)
        .filter(
            Incident.correlation_id == correlation_id,
            Incident.status.in_(ACTIVE_INCIDENT_STATUSES),
        )
        .first()
    )

    now = datetime.utcnow()

    if incident:
        incident.updated_at = now

        event = IncidentEvent(
            incident_id=incident.id,
            event_type="INCIDENT_ALERT_ATTACHED",
            message="Additional telemetry alert attached to existing incident.",
            event_metadata=alert_event,
            created_at=now,
        )

        db.add(event)
        db.commit()
        db.refresh(incident)

        publish_incident_event(
            "INCIDENT_ALERT_ATTACHED",
            {
                "incident_id": str(incident.id),
                "correlation_id": incident.correlation_id,
                "service_id": incident.service_id,
                "environment": incident.environment,
                "alert_event": alert_event,
            },
        )

        return incident

    incident = Incident(
        title=_build_title(alert_event),
        description=_build_description(alert_event),
        severity=_severity_from_alert(alert_event.get("severity")),
        status=IncidentStatus.OPEN,
        service_id=str(alert_event.get("service_id")),
        environment=alert_event.get("environment", "unknown"),
        correlation_id=correlation_id,
        triggered_by_event_id=alert_event.get("event_id"),
        started_at=now,
        created_at=now,
        updated_at=now,
    )

    db.add(incident)
    db.flush()

    event = IncidentEvent(
        incident_id=incident.id,
        event_type="INCIDENT_CREATED",
        message="Incident created from telemetry alert.",
        event_metadata=alert_event,
        created_at=now,
    )

    db.add(event)
    db.commit()
    db.refresh(incident)

    publish_incident_event(
        "INCIDENT_CREATED",
        {
            "incident_id": str(incident.id),
            "title": incident.title,
            "severity": incident.severity.value,
            "status": incident.status.value,
            "service_id": incident.service_id,
            "environment": incident.environment,
            "correlation_id": incident.correlation_id,
            "triggered_by_event_id": incident.triggered_by_event_id,
        },
    )

    return incident


def acknowledge_incident(db: Session, incident_id: UUID) -> Incident:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if not incident:
        raise ValueError("Incident not found")

    if incident.status == IncidentStatus.RESOLVED:
        raise ValueError("Resolved incidents cannot be acknowledged")

    now = datetime.utcnow()

    incident.status = IncidentStatus.ACKNOWLEDGED
    incident.updated_at = now

    event = IncidentEvent(
        incident_id=incident.id,
        event_type="INCIDENT_ACKNOWLEDGED",
        message="Incident acknowledged.",
        event_metadata={},
        created_at=now,
    )

    db.add(event)
    db.commit()
    db.refresh(incident)

    publish_incident_event(
        "INCIDENT_ACKNOWLEDGED",
        {
            "incident_id": str(incident.id),
            "service_id": incident.service_id,
            "environment": incident.environment,
            "status": incident.status.value,
        },
    )

    return incident


def resolve_incident(db: Session, incident_id: UUID) -> Incident:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if not incident:
        raise ValueError("Incident not found")

    now = datetime.utcnow()

    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = now
    incident.updated_at = now

    event = IncidentEvent(
        incident_id=incident.id,
        event_type="INCIDENT_RESOLVED",
        message="Incident resolved.",
        event_metadata={},
        created_at=now,
    )

    db.add(event)
    db.commit()
    db.refresh(incident)

    publish_incident_event(
        "INCIDENT_RESOLVED",
        {
            "incident_id": str(incident.id),
            "service_id": incident.service_id,
            "environment": incident.environment,
            "status": incident.status.value,
            "resolved_at": incident.resolved_at.isoformat(),
        },
    )

    return incident


def build_incident_timeline(db: Session, incident: Incident) -> list[dict[str, Any]]:
    """
    MVP timeline.

    It includes:
    - incident events
    - recent service health snapshots
    - latest pipeline/deployment rows if your models exist

    This gives you Sprint 5F behavior without needing to perfectly unify every Kafka topic yet.
    """

    timeline: list[dict[str, Any]] = []

    for event in incident.events:
        timeline.append(
            {
                "timestamp": event.created_at,
                "source": "incident.events",
                "event_type": event.event_type,
                "title": event.message or event.event_type,
                "details": event.event_metadata or {},
            }
        )

    # Add recent service health snapshots if the model exists.
    try:
        from app.models import ServiceHealthSnapshot

        start_time = incident.started_at - timedelta(minutes=60)
        end_time = incident.resolved_at or datetime.utcnow()

        snapshots = (
            db.query(ServiceHealthSnapshot)
            .filter(
                ServiceHealthSnapshot.service_id == incident.service_id,
                ServiceHealthSnapshot.environment == incident.environment,
                ServiceHealthSnapshot.created_at >= start_time,
                ServiceHealthSnapshot.created_at <= end_time,
            )
            .order_by(ServiceHealthSnapshot.created_at.asc())
            .limit(25)
            .all()
        )

        for snapshot in snapshots:
            timeline.append(
                {
                    "timestamp": snapshot.created_at,
                    "source": "telemetry.alerts",
                    "event_type": "SERVICE_HEALTH_SNAPSHOT",
                    "title": f"Service health status: {snapshot.status}",
                    "details": {
                        "status": str(snapshot.status),
                        "latency_ms": snapshot.latency_ms,
                        "error_rate": snapshot.error_rate,
                        "pod_restart_count": snapshot.pod_restart_count,
                        "replica_count": snapshot.replica_count,
                        "available_replicas": snapshot.available_replicas,
                    },
                }
            )
    except Exception:
        logger.exception("Could not attach service health snapshots to timeline")

    # Add latest pipeline history if PipelineRun has service_id.
    try:
        import app.models as models

        PipelineRun = getattr(models, "PipelineRun", None)

        if PipelineRun is not None and hasattr(PipelineRun, "service_id"):
            runs = (
                db.query(PipelineRun)
                .filter(PipelineRun.service_id == incident.service_id)
                .order_by(PipelineRun.created_at.desc())
                .limit(5)
                .all()
            )

            for run in runs:
                timestamp = (
                    getattr(run, "completed_at", None)
                    or getattr(run, "updated_at", None)
                    or getattr(run, "created_at", None)
                )

                timeline.append(
                    {
                        "timestamp": timestamp,
                        "source": "pipeline.events",
                        "event_type": "PIPELINE_RUN",
                        "title": f"Pipeline run {getattr(run, 'status', 'UNKNOWN')}",
                        "details": {
                            "pipeline_run_id": str(run.id),
                            "status": str(getattr(run, "status", None)),
                            "stage": str(getattr(run, "stage", None)),
                            "risk_level": str(getattr(run, "risk_level", None)),
                            "risk_score": getattr(run, "risk_score", None),
                        },
                    }
                )
    except Exception:
        logger.exception("Could not attach pipeline runs to timeline")

    # Add latest deployment history if DeploymentRun exists.
    try:
        import app.models as models

        DeploymentRun = getattr(models, "DeploymentRun", None)

        if DeploymentRun is not None and hasattr(DeploymentRun, "service_id"):
            deployments = (
                db.query(DeploymentRun)
                .filter(DeploymentRun.service_id == incident.service_id)
                .order_by(DeploymentRun.created_at.desc())
                .limit(5)
                .all()
            )

            for deployment in deployments:
                timestamp = (
                    getattr(deployment, "completed_at", None)
                    or getattr(deployment, "updated_at", None)
                    or getattr(deployment, "created_at", None)
                )

                timeline.append(
                    {
                        "timestamp": timestamp,
                        "source": "deployment.events",
                        "event_type": "DEPLOYMENT_RUN",
                        "title": f"Deployment {getattr(deployment, 'status', 'UNKNOWN')}",
                        "details": {
                            "deployment_id": str(deployment.id),
                            "status": str(getattr(deployment, "status", None)),
                            "environment": getattr(deployment, "environment", None),
                        },
                    }
                )
    except Exception:
        logger.exception("Could not attach deployments to timeline")

    timeline = [item for item in timeline if item.get("timestamp") is not None]
    timeline.sort(key=lambda item: item["timestamp"])

    return timeline