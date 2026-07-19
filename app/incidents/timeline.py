from app.models import IncidentStatus


RELIABILITY_ALERT_CREATED = "RELIABILITY_ALERT_CREATED"
INCIDENT_CREATED = "INCIDENT_CREATED"
ALERT_ATTACHED = "ALERT_ATTACHED"
DEPLOYMENT_RELEASED = "DEPLOYMENT_RELEASED"
DEPLOYMENT_CORRELATED = "DEPLOYMENT_CORRELATED"
SEVERITY_ESCALATED = "SEVERITY_ESCALATED"

INCIDENT_ACKNOWLEDGED = "INCIDENT_ACKNOWLEDGED"
INCIDENT_ASSIGNED = "INCIDENT_ASSIGNED"
INVESTIGATION_STARTED = "INVESTIGATION_STARTED"
ACTION_RECOMMENDED = "ACTION_RECOMMENDED"
REMEDIATION_STARTED = "REMEDIATION_STARTED"
RECOVERY_FAILED = "RECOVERY_FAILED"
INCIDENT_RESOLVED = "INCIDENT_RESOLVED"

INCIDENT_COMMENT_ADDED = "INCIDENT_COMMENT_ADDED"
INCIDENT_STATUS_CHANGED = "INCIDENT_STATUS_CHANGED"


STATUS_TIMELINE_EVENT_TYPES: dict[IncidentStatus, str] = {
    IncidentStatus.ACKNOWLEDGED: INCIDENT_ACKNOWLEDGED,
    IncidentStatus.INVESTIGATING: INVESTIGATION_STARTED,
    IncidentStatus.ACTION_RECOMMENDED: ACTION_RECOMMENDED,
    IncidentStatus.REMEDIATING: REMEDIATION_STARTED,
    IncidentStatus.FAILED_RECOVERY: RECOVERY_FAILED,
    IncidentStatus.RESOLVED: INCIDENT_RESOLVED,
}


STATUS_TIMELINE_MESSAGES: dict[IncidentStatus, str] = {
    IncidentStatus.ACKNOWLEDGED: "Incident acknowledged",
    IncidentStatus.INVESTIGATING: "Investigation started",
    IncidentStatus.ACTION_RECOMMENDED: "Action recommendation recorded",
    IncidentStatus.REMEDIATING: "Remediation started",
    IncidentStatus.FAILED_RECOVERY: "Recovery attempt failed",
    IncidentStatus.RESOLVED: "Incident resolved",
}


def get_status_timeline_event_type(status: IncidentStatus) -> str:
    return STATUS_TIMELINE_EVENT_TYPES.get(
        status,
        INCIDENT_STATUS_CHANGED,
    )


def get_status_timeline_message(
    status: IncidentStatus,
    actor_name: str | None = None,
) -> str:
    message = STATUS_TIMELINE_MESSAGES.get(
        status,
        f"Incident status changed to {status.value}",
    )

    if actor_name:
        return f"{message} by {actor_name}"

    return message


def get_actor_display_name(actor) -> str:
    if actor is None:
        return "PlatformIQ"

    return (
        getattr(actor, "full_name", None)
        or getattr(actor, "email", None)
        or str(actor.id)
    )

def get_timeline_event_type(status) -> str:
    """
    Return the canonical timeline event type for an incident status.
    """

    status_value = getattr(status, "value", status)

    event_types = {
        "DETECTED": "INCIDENT_DETECTED",
        "ACKNOWLEDGED": "INCIDENT_ACKNOWLEDGED",
        "INVESTIGATING": "INCIDENT_INVESTIGATING",
        "ACTION_RECOMMENDED": (
            "INCIDENT_ACTION_RECOMMENDED"
        ),
        "REMEDIATING": "INCIDENT_REMEDIATING",
        "RESOLVED": "INCIDENT_RESOLVED",
        "FAILED_RECOVERY": "INCIDENT_FAILED_RECOVERY",
    }

    try:
        return event_types[str(status_value)]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported incident status: {status_value}"
        ) from exc
