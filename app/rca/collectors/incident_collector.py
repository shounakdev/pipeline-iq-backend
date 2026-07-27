from sqlalchemy.orm import Session

from app.models import (
    Incident,
    IncidentAlertLink,
    IncidentMetric,
    IncidentTimelineEvent,
)


def collect_incident_evidence(db: Session, incident_id) -> dict:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if not incident:
        return {
            "status": "NO_DATA",
            "reason": "Incident not found",
        }

    alert_links = (
        db.query(IncidentAlertLink)
        .filter(IncidentAlertLink.incident_id == incident.id)
        .all()
    )

    timeline_events = (
        db.query(IncidentTimelineEvent)
        .filter(IncidentTimelineEvent.incident_id == incident.id)
        .order_by(
            IncidentTimelineEvent.occurred_at.asc(),
            IncidentTimelineEvent.id.asc(),
        )
        .all()
    )

    metrics = (
        db.query(IncidentMetric)
        .filter(IncidentMetric.incident_id == incident.id)
        .all()
    )

    related_alert_ids = []

    triggering_alert_id = getattr(incident, "triggering_alert_id", None)
    if triggering_alert_id:
        related_alert_ids.append(str(triggering_alert_id))

    related_alert_ids.extend(
        str(link.reliability_alert_id)
        for link in alert_links
        if getattr(link, "reliability_alert_id", None)
    )

    return {
        "status": "COLLECTED",
        "incident_id": str(incident.id),
        "incident_number": getattr(incident, "incident_number", None),
        "title": getattr(incident, "title", None),
        "severity": _enum_value(getattr(incident, "severity", None)),
        "incident_status": _enum_value(getattr(incident, "status", None)),
        "primary_service_id": _string_or_none(
            getattr(incident, "primary_service_id", None)
        ),
        "environment": getattr(incident, "environment", None),
        "failure_started_at": getattr(incident, "failure_started_at", None),
        "detected_at": getattr(incident, "detected_at", None),
        "acknowledged_at": getattr(incident, "acknowledged_at", None),
        "resolved_at": getattr(incident, "resolved_at", None),
        "suspected_deployment_id": _string_or_none(
            getattr(incident, "suspected_deployment_id", None)
        ),
        "related_alert_ids": sorted(set(related_alert_ids)),
        "timeline_events": [
            {
                "event_type": _enum_value(getattr(event, "event_type", None)),
                "occurred_at": getattr(event, "occurred_at", None),
                "summary": getattr(event, "summary", None),
                "source": getattr(event, "source", None),
            }
            for event in timeline_events
        ],
        "metrics": [
            {
                "metric_name": getattr(metric, "metric_name", None),
                "metric_value": getattr(metric, "metric_value", None),
                "unit": getattr(metric, "unit", None),
                "captured_at": getattr(metric, "captured_at", None),
            }
            for metric in metrics
        ],
        "human_context_included": False,
    }


def _enum_value(value):
    if value is None:
        return None
    return getattr(value, "value", value)


def _string_or_none(value):
    if value is None:
        return None
    return str(value)