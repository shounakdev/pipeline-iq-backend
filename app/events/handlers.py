from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.events.constants import EVENT_TOPIC_MAP
from app.models import EventRecord, Incident


SUPPORTED_EVENT_TYPES = set(EVENT_TOPIC_MAP.keys())


def handle_event(db: Session, record: EventRecord) -> None:
    """
    Handles side effects after an event has been consumed.

    Sprint 5D:
    - telemetry.alerts events create incidents.
    """

    if record.event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(f"Unsupported event_type={record.event_type}")

    if record.topic == "deployment.events":
        handle_deployment_event(db, record)

    elif record.topic == "kubernetes.events":
        handle_kubernetes_event(db, record)

    elif record.topic == "audit.events":
        handle_audit_event(db, record)

    elif record.topic == "telemetry.alerts":
        handle_telemetry_alert_event(db, record)

    record.processing_status = "PROCESSED"
    record.processing_error = None
    record.processed_at = datetime.now(timezone.utc)


def handle_deployment_event(db: Session, record: EventRecord) -> None:
    payload = record.payload or {}
    deployment_id = payload.get("deployment_id")

    if not deployment_id:
        return

    try:
        import app.models as models

        DeploymentRun = getattr(models, "DeploymentRun", None)

        if DeploymentRun is None:
            return

        deployment = db.query(DeploymentRun).filter(
            DeploymentRun.id == deployment_id
        ).first()

        if deployment is None:
            raise ValueError(f"DeploymentRun not found for deployment_id={deployment_id}")

        if record.event_type.endswith("_STARTED"):
            deployment.status = "RUNNING"
        elif record.event_type.endswith("_COMPLETED"):
            deployment.status = "SUCCESS"
        elif record.event_type.endswith("_FAILED"):
            deployment.status = "FAILED"

    except ValueError:
        raise
    except Exception:
        return


def handle_kubernetes_event(db: Session, record: EventRecord) -> None:
    return


def handle_audit_event(db: Session, record: EventRecord) -> None:
    return


def handle_telemetry_alert_event(db: Session, record: EventRecord) -> None:
    """
    Converts observability alert events into incidents.
    """

    payload = record.payload or {}
    raw_event = record.raw_event or {}

    severity = payload.get("severity", "MEDIUM")
    snapshot_id = payload.get("snapshot_id")

    if not severity:
        raise ValueError(f"Telemetry alert missing severity for event_id={record.event_id}")

    if not snapshot_id:
        raise ValueError(f"Telemetry alert missing snapshot_id for event_id={record.event_id}")

    existing = db.query(Incident).filter(
        Incident.source_event_id == record.event_id
    ).first()

    if existing:
        return

    service_name = raw_event.get("service_name") or record.service_id or "unknown-service"
    environment = raw_event.get("environment") or record.environment or "unknown"

    title = f"{service_name} - {record.event_type}"

    description = build_incident_description(
        event_type=record.event_type,
        service_name=service_name,
        environment=environment,
        payload=payload,
    )

    incident = Incident(
        title=title,
        description=description,
        service_id=record.service_id,
        service_name=service_name,
        environment=environment,
        severity=severity,
        status="OPEN",
        incident_type=record.event_type,
        source="platformiq-observability",
        source_event_id=record.event_id,
        correlation_id=record.correlation_id,
        snapshot_id=snapshot_id,
        payload=payload,
        raw_event=raw_event,
    )

    db.add(incident)


def build_incident_description(
    *,
    event_type: str,
    service_name: str,
    environment: str,
    payload: dict,
) -> str:
    if event_type == "HIGH_ERROR_RATE":
        return (
            f"{service_name} in {environment} is experiencing high error rate. "
            f"Observed error rate: {payload.get('error_rate')}%. "
            f"Threshold: {payload.get('threshold_percent')}%."
        )

    if event_type == "HIGH_LATENCY":
        return (
            f"{service_name} in {environment} is experiencing high latency. "
            f"Observed latency: {payload.get('latency_ms')} ms. "
            f"Threshold: {payload.get('threshold_ms')} ms."
        )

    if event_type == "POD_RESTART_SPIKE":
        return (
            f"{service_name} in {environment} has a pod restart spike. "
            f"Observed restarts: {payload.get('pod_restart_count')}. "
            f"Threshold: {payload.get('threshold')}."
        )

    if event_type == "SERVICE_DEGRADED":
        return (
            f"{service_name} in {environment} is degraded. "
            f"Available replicas: {payload.get('available_replicas')}. "
            f"Expected replicas: {payload.get('replica_count')}."
        )

    if event_type == "SERVICE_DOWN":
        return f"{service_name} in {environment} appears to be down."

    return f"{service_name} in {environment} triggered alert {event_type}."