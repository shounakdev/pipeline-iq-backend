import json
import uuid
from datetime import datetime, timezone

from app.observability.alert_rules import evaluate_alerts
from app.incidents.incident_service import create_or_update_incident_from_alert


TELEMETRY_ALERTS_TOPIC = "telemetry.alerts"


def build_alert_event(snapshot, alert, correlation_id: str | None = None):
    """
    Build a telemetry alert event from a service health snapshot.

    This event is used for:
    1. Publishing to Kafka topic: telemetry.alerts
    2. Creating/updating incidents
    """

    alert_correlation_id = (
        correlation_id
        or f"{snapshot.service_id}:{snapshot.environment}:{alert.event_type}"
    )

    return {
        "event_id": f"evt_{uuid.uuid4()}",
        "event_type": alert.event_type,
        "schema_version": "1.0",
        "severity": alert.severity,
        "correlation_id": alert_correlation_id,
        "service_id": str(snapshot.service_id),
        "service_name": snapshot.service_name,
        "environment": snapshot.environment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            **alert.payload,
            "severity": alert.severity,
            "source": "platformiq-observability",
            "snapshot_id": str(snapshot.id),
        },
    }


def emit_alerts_for_snapshot(
    snapshot,
    kafka_producer,
    db,
    correlation_id: str | None = None,
):
    """
    Evaluate alert rules for a snapshot, publish alert events to Kafka,
    and create/update incidents from those alerts.
    """

    alerts = evaluate_alerts(snapshot)

    emitted_events = []

    for alert in alerts:
        event = build_alert_event(
            snapshot=snapshot,
            alert=alert,
            correlation_id=correlation_id,
        )

        # Existing Sprint 5D behavior:
        # Publish alert to Kafka
        kafka_producer.produce(
            TELEMETRY_ALERTS_TOPIC,
            key=str(snapshot.service_id),
            value=json.dumps(event).encode("utf-8"),
        )

        # New Sprint 5E behavior:
        # Convert alert into incident
        create_or_update_incident_from_alert(db, event)

        emitted_events.append(event)

    kafka_producer.flush()

    return emitted_events