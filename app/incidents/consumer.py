"""Reliability-alert event consumer for incident creation and updates."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.incidents import repository
from app.incidents.service import (
    create_or_update_incident_from_alert,
)
from app.models import (
    EventRecord,
    ReliabilityAlert,
    ReliabilityAlertStatus,
)


ACTIVE_RELIABILITY_ALERT_STATUSES = {
    ReliabilityAlertStatus.OPEN,
    ReliabilityAlertStatus.ACKNOWLEDGED,
}


def _get_payload(record: EventRecord) -> dict[str, Any]:
    """Return a safe event payload."""

    if isinstance(record.payload, dict):
        return record.payload

    return {}


def _get_alert_id(
    record: EventRecord,
    payload: dict[str, Any],
) -> str:
    """
    Extract the reliability-alert ID.

    alert_id is the Sprint 7D field. reliability_alert_id is
    temporarily supported for events produced before Sprint 7D.
    """

    alert_id = (
        payload.get("alert_id")
        or payload.get("reliability_alert_id")
    )

    if not alert_id:
        raise ValueError(
            "Reliability alert event is missing alert_id: "
            f"event_id={record.event_id}"
        )

    return str(alert_id)


def _optional_int(
    payload: dict[str, Any],
    key: str,
    default: int,
) -> int:
    value = payload.get(key)

    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid {key} in reliability alert event"
        ) from exc


def _optional_float(
    payload: dict[str, Any],
    key: str,
) -> float | None:
    value = payload.get(key)

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid {key} in reliability alert event"
        ) from exc


def process_reliability_alert_event(
    db: Session,
    record: EventRecord,
):
    """
    Convert one consumed reliability-alert event into an incident.

    Processing steps:

    1. Extract the alert ID.
    2. Load the authoritative ReliabilityAlert from the database.
    3. Return the existing incident when the alert was already linked.
    4. Ignore stale resolved alerts that were never linked.
    5. Delegate all incident rules and writes to the incident service.

    This function does not commit. Transaction management remains in
    the incident service and the platform event consumer.
    """

    payload = _get_payload(record)
    alert_id = _get_alert_id(record, payload)

    alert = (
        db.query(ReliabilityAlert)
        .filter(ReliabilityAlert.id == alert_id)
        .first()
    )

    if alert is None:
        raise ValueError(
            "ReliabilityAlert not found: "
            f"alert_id={alert_id}, event_id={record.event_id}"
        )

    existing_link = (
        repository.get_incident_alert_link_by_alert_id(
            db,
            alert_id,
        )
    )

    environment = (
        record.environment
        or payload.get("environment")
    )

    if not environment:
        raise ValueError(
            "Reliability alert event is missing environment: "
            f"alert_id={alert_id}, event_id={record.event_id}"
        )

    # An already-linked alert remains idempotent even if the alert
    # was later resolved.
    if existing_link is not None:
        return create_or_update_incident_from_alert(
            db,
            alert,
            environment=str(environment),
        )

    alert_status = ReliabilityAlertStatus(alert.status)

    # A stale event may arrive after the underlying alert recovered.
    # It is not a worker failure and must not create a new incident.
    if alert_status not in ACTIVE_RELIABILITY_ALERT_STATUSES:
        return None

    affected_service_count = _optional_int(
        payload,
        "affected_service_count",
        1,
    )

    high_severity_alert_count = _optional_int(
        payload,
        "high_severity_alert_count",
        0,
    )

    availability_percent = _optional_float(
        payload,
        "availability_percent",
    )

    return create_or_update_incident_from_alert(
        db,
        alert,
        environment=str(environment),
        affected_service_count=affected_service_count,
        availability_percent=availability_percent,
        high_severity_alert_count=(
            high_severity_alert_count
        ),
    )