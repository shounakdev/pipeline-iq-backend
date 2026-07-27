from sqlalchemy.orm import Session

from app.models import ReliabilityAlert


def collect_slo_evidence(db: Session, incident: dict) -> dict:
    service_id = incident.get("primary_service_id")
    related_alert_ids = incident.get("related_alert_ids") or []

    alert = None

    if related_alert_ids:
        alert = (
            db.query(ReliabilityAlert)
            .filter(ReliabilityAlert.id.in_(related_alert_ids))
            .order_by(ReliabilityAlert.created_at.desc())
            .first()
        )

    if alert is None and service_id:
        alert = (
            db.query(ReliabilityAlert)
            .filter(ReliabilityAlert.service_id == service_id)
            .order_by(ReliabilityAlert.created_at.desc())
            .first()
        )

    if alert is None:
        return {
            "status": "NO_DATA",
            "reason": "No SLO or reliability alert found for incident",
        }

    return {
        "status": "COLLECTED",
        "reliability_alert_id": str(alert.id),
        "slo_definition_id": _string_or_none(
            getattr(alert, "slo_definition_id", None)
        ),
        "slo_type": _enum_value(getattr(alert, "slo_type", None)),
        "target": getattr(alert, "target", None),
        "measured_value": getattr(alert, "measured_value", None),
        "window_minutes": getattr(alert, "window_minutes", None),
        "breach_status": _enum_value(getattr(alert, "breach_status", None)),
        "burn_rate": getattr(alert, "burn_rate", None),
        "error_budget_status": _enum_value(
            getattr(alert, "error_budget_status", None)
        ),
        "alert_severity": _enum_value(getattr(alert, "severity", None)),
        "breach_started_at": getattr(alert, "breach_started_at", None),
        "created_at": getattr(alert, "created_at", None),
    }


def _enum_value(value):
    if value is None:
        return None
    return getattr(value, "value", value)


def _string_or_none(value):
    if value is None:
        return None
    return str(value)