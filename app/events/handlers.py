from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.events.constants import (
    EVENT_TOPIC_MAP,
    RELIABILITY_ALERT_CREATED,
    TOPIC_TELEMETRY_ALERTS,
)
from app.incidents.consumer import (
    process_reliability_alert_event,
)
from app.models import (
    EventRecord,
    Incident,
    IncidentSeverity,
    IncidentStatus,
)


SUPPORTED_EVENT_TYPES = set(EVENT_TOPIC_MAP.keys())


LEGACY_SEVERITY_MAP = {
    "CRITICAL": IncidentSeverity.SEV_1,
    "SEV-1": IncidentSeverity.SEV_1,
    "SEV_1": IncidentSeverity.SEV_1,
    "HIGH": IncidentSeverity.SEV_2,
    "SEV-2": IncidentSeverity.SEV_2,
    "SEV_2": IncidentSeverity.SEV_2,
    "MEDIUM": IncidentSeverity.SEV_3,
    "LOW": IncidentSeverity.SEV_3,
    "SEV-3": IncidentSeverity.SEV_3,
    "SEV_3": IncidentSeverity.SEV_3,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def dictionary_value(value: Any) -> dict[str, Any]:
    """
    Return a dictionary for JSON payload fields.

    Event payloads should normally already be dictionaries, but this
    prevents malformed data from causing attribute errors before the
    event can be marked as failed by the consumer.
    """

    if isinstance(value, dict):
        return value

    return {}


def normalize_legacy_severity(
    severity: Any,
) -> IncidentSeverity:
    """
    Convert Sprint 5 severity values into the Sprint 7 severity model.
    """

    raw_value = getattr(severity, "value", severity)

    if raw_value is None:
        return IncidentSeverity.SEV_3

    normalized_value = str(raw_value).strip().upper()

    return LEGACY_SEVERITY_MAP.get(
        normalized_value,
        IncidentSeverity.SEV_3,
    )


def validate_event_topic(record: EventRecord) -> None:
    """
    Confirm that the event was consumed from its configured topic.
    """

    expected_topic = EVENT_TOPIC_MAP.get(
        record.event_type
    )

    if expected_topic is None:
        raise ValueError(
            f"Unsupported event_type={record.event_type}"
        )

    if record.topic != expected_topic:
        raise ValueError(
            "Event topic does not match the configured topic: "
            f"event_type={record.event_type}, "
            f"expected_topic={expected_topic}, "
            f"actual_topic={record.topic}"
        )


def handle_event(
    db: Session,
    record: EventRecord,
) -> None:
    """
    Dispatch a consumed platform event to its domain handler.

    Sprint 5:
    - Process deployment, Kubernetes, audit and observability events.
    - Convert legacy observability alerts into incidents.

    Sprint 7:
    - Route reliability-alert events through the current incident
      response engine.

    Transaction commit and rollback are managed by the event consumer.
    """

    validate_event_topic(record)

    if record.topic == "deployment.events":
        handle_deployment_event(db, record)

    elif record.topic == "kubernetes.events":
        handle_kubernetes_event(db, record)

    elif record.topic == "audit.events":
        handle_audit_event(db, record)

    elif record.topic == TOPIC_TELEMETRY_ALERTS:
        handle_telemetry_alert(db, record)

    else:
        raise ValueError(
            f"Unsupported event topic={record.topic}"
        )

    record.processing_status = "PROCESSED"
    record.processing_error = None
    record.processed_at = utc_now()


def handle_deployment_event(
    db: Session,
    record: EventRecord,
) -> None:
    """
    Update a deployment run from a deployment lifecycle event.

    DeploymentRun is resolved dynamically to preserve compatibility
    with installations where that model has not yet been introduced.
    """

    payload = dictionary_value(record.payload)
    deployment_id = payload.get("deployment_id")

    if not deployment_id:
        return

    try:
        import app.models as models

        deployment_run_model = getattr(
            models,
            "DeploymentRun",
            None,
        )

        if deployment_run_model is None:
            return

        deployment = (
            db.query(deployment_run_model)
            .filter(
                deployment_run_model.id
                == deployment_id
            )
            .first()
        )

        if deployment is None:
            raise ValueError(
                "DeploymentRun not found for "
                f"deployment_id={deployment_id}"
            )

        if record.event_type.endswith("_STARTED"):
            deployment.status = "RUNNING"

        elif record.event_type.endswith("_COMPLETED"):
            deployment.status = "SUCCESS"

        elif record.event_type.endswith("_FAILED"):
            deployment.status = "FAILED"

    except ValueError:
        raise

    except Exception as exc:
        raise RuntimeError(
            "Failed to process deployment event "
            f"event_id={record.event_id}"
        ) from exc


def handle_telemetry_alert(
    db: Session,
    record: EventRecord,
) -> None:
    """
    Route telemetry events to the appropriate incident flow.

    Sprint 6 reliability-alert events use the Sprint 7 incident
    consumer. Legacy Sprint 5 observability alerts retain their
    compatibility handler.
    """

    if record.event_type == RELIABILITY_ALERT_CREATED:
        process_reliability_alert_event(
            db,
            record,
        )
        return

    handle_telemetry_alert_event(
        db,
        record,
    )


def handle_kubernetes_event(
    db: Session,
    record: EventRecord,
) -> None:
    """
    Placeholder for Kubernetes event side effects.
    """

    return


def handle_audit_event(
    db: Session,
    record: EventRecord,
) -> None:
    """
    Placeholder for audit event side effects.
    """

    return


def handle_telemetry_alert_event(
    db: Session,
    record: EventRecord,
) -> None:
    """
    Convert a legacy Sprint 5 observability alert into an incident.

    The incident uses the current Sprint 7 status, severity and
    correlation fields while preserving legacy compatibility fields.
    """

    payload = dictionary_value(record.payload)
    raw_event = dictionary_value(record.raw_event)

    snapshot_id = payload.get("snapshot_id")

    if not snapshot_id:
        raise ValueError(
            "Telemetry alert missing snapshot_id for "
            f"event_id={record.event_id}"
        )

    if not record.service_id:
        raise ValueError(
            "Telemetry alert missing service_id for "
            f"event_id={record.event_id}"
        )

    incident_severity = normalize_legacy_severity(
        payload.get("severity", "MEDIUM")
    )

    deduplication_key = (
        "legacy-observability:"
        f"{record.event_id}"
    )

    existing_incident = (
        db.query(Incident)
        .filter(
            (
                Incident.deduplication_key
                == deduplication_key
            )
            | (
                Incident.source_event_id
                == record.event_id
            )
        )
        .first()
    )

    if existing_incident is not None:
        return

    service_name = (
        raw_event.get("service_name")
        or record.service_id
        or "unknown-service"
    )

    environment = (
        raw_event.get("environment")
        or record.environment
        or "unknown"
    )

    detected_at = (
        getattr(record, "occurred_at", None)
        or getattr(record, "created_at", None)
        or utc_now()
    )

    title = (
        f"{service_name} - {record.event_type}"
    )

    description = build_incident_description(
        event_type=record.event_type,
        service_name=service_name,
        environment=environment,
        payload=payload,
    )

    incident = Incident(
        title=title,
        description=description,

        # Current Sprint 7 incident fields.
        severity=incident_severity,
        status=IncidentStatus.DETECTED,
        primary_service_id=record.service_id,
        service_id=record.service_id,
        environment=environment,
        deduplication_key=deduplication_key,
        triggered_by_event_id=record.event_id,
        failure_started_at=detected_at,
        detected_at=detected_at,
        correlation_id=(
            record.correlation_id
            or deduplication_key
        ),

        # Legacy Sprint 5 compatibility fields.
        service_name=service_name,
        incident_type=record.event_type,
        source="platformiq-observability",
        source_event_id=record.event_id,
        snapshot_id=snapshot_id,
        payload=payload,
        raw_event=raw_event,
    )

    db.add(incident)
    db.flush()


def build_incident_description(
    *,
    event_type: str,
    service_name: str,
    environment: str,
    payload: dict[str, Any],
) -> str:
    """
    Build a human-readable description for legacy observability alerts.
    """

    if event_type == "HIGH_ERROR_RATE":
        return (
            f"{service_name} in {environment} is experiencing "
            "a high error rate. "
            f"Observed error rate: "
            f"{payload.get('error_rate')}%. "
            f"Threshold: "
            f"{payload.get('threshold_percent')}%."
        )

    if event_type == "HIGH_LATENCY":
        return (
            f"{service_name} in {environment} is experiencing "
            "high latency. "
            f"Observed latency: "
            f"{payload.get('latency_ms')} ms. "
            f"Threshold: "
            f"{payload.get('threshold_ms')} ms."
        )

    if event_type == "POD_RESTART_SPIKE":
        return (
            f"{service_name} in {environment} has a pod "
            "restart spike. "
            f"Observed restarts: "
            f"{payload.get('pod_restart_count')}. "
            f"Threshold: {payload.get('threshold')}."
        )

    if event_type == "SERVICE_DEGRADED":
        return (
            f"{service_name} in {environment} is degraded. "
            f"Available replicas: "
            f"{payload.get('available_replicas')}. "
            f"Expected replicas: "
            f"{payload.get('replica_count')}."
        )

    if event_type == "SERVICE_DOWN":
        return (
            f"{service_name} in {environment} appears "
            "to be down."
        )

    return (
        f"{service_name} in {environment} triggered "
        f"alert {event_type}."
    )