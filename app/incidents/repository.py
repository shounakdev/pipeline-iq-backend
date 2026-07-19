from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid
from uuid import UUID
import json
from sqlalchemy import func, select
from sqlalchemy.orm import Session



from app.models import (
    AuditEvent,
    Deployment,
    Environment,
    ErrorBudgetStatus,
    Incident,
    IncidentAlertLink,
    IncidentAssignment,
    IncidentComment,
    IncidentMetric,
    IncidentSeverity,
    IncidentStatus,
    IncidentTimelineEvent,
    ReliabilityAlert,
    SLOMeasurement,
    User,
)


# ---------------------------------------------------------------------------
# Incident read functions
# ---------------------------------------------------------------------------


def get_incidents_for_metrics(
    db: Session,
):
    statement = select(
        Incident.failure_started_at,
        Incident.detected_at,
        Incident.acknowledged_at,
        Incident.resolved_at,
        Incident.status,
        Incident.severity,
    )

    return db.execute(statement).all()



def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enum_value(value: Any) -> Any:
    """Return an enum's persisted value while leaving plain values alone."""
    return getattr(value, "value", value)


def get_incident_by_id(
    db: Session,
    incident_id: UUID,
    *,
    for_update: bool = False,
) -> Incident | None:
    """Return one incident by UUID, optionally locking it for mutation."""
    statement = select(Incident).where(
        Incident.id == incident_id,
    )

    if for_update:
        statement = statement.with_for_update()

    return db.execute(statement).scalar_one_or_none()


def get_user_by_id(
    db: Session,
    user_id: str,
) -> User | None:
    """Return the assignment target user without changing the session."""
    statement = select(User).where(
        User.id == user_id,
    )

    return db.execute(statement).scalar_one_or_none()


def get_incident_by_number(
    db: Session,
    incident_number: str,
) -> Incident | None:
    """
    Return one incident by its human-readable incident number.
    """

    statement = select(Incident).where(
        Incident.incident_number == incident_number,
    )

    return db.execute(statement).scalar_one_or_none()

def get_incident_alert_link_by_alert_id(
    db: Session,
    reliability_alert_id: str,
) -> IncidentAlertLink | None:
    """
    Return the incident link for a reliability alert.

    A reliability alert must only be processed by the incident
    workflow once, even when its event is delivered repeatedly.
    """

    statement = (
        select(IncidentAlertLink)
        .where(
            IncidentAlertLink.reliability_alert_id
            == reliability_alert_id,
        )
        .order_by(
            IncidentAlertLink.linked_at.asc(),
        )
        .limit(1)
    )

    return db.execute(statement).scalar_one_or_none()


def list_incidents(
    db: Session,
    *,
    status: IncidentStatus | str | None = None,
    severity: IncidentSeverity | str | None = None,
    service_id: str | None = None,
    environment: str | None = None,
    assignee_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[Incident], int]:
    """
    Return a paginated collection of incidents and the total number of
    incidents matching the supplied filters.
    """

    statement = select(Incident)

    count_statement = (
        select(
            func.count(
                func.distinct(Incident.id),
            ),
        )
        .select_from(Incident)
    )

    filters = []

    if status is not None:
        filters.append(
            Incident.status == status,
        )

    if severity is not None:
        filters.append(
            Incident.severity == severity,
        )

    if service_id is not None:
        filters.append(
            Incident.primary_service_id == service_id,
        )

    if environment is not None:
        filters.append(
            Incident.environment == environment,
        )

    if from_date is not None:
        filters.append(
            Incident.detected_at >= from_date,
        )

    if to_date is not None:
        filters.append(
            Incident.detected_at <= to_date,
        )

    if assignee_id is not None:
        active_assignment_incident_ids = (
            select(
                IncidentAssignment.incident_id,
            )
            .where(
                IncidentAssignment.assigned_to_user_id
                == assignee_id,
                IncidentAssignment.is_active.is_(True),
            )
        )

        filters.append(
            Incident.id.in_(
                active_assignment_incident_ids,
            ),
        )

    if filters:
        statement = statement.where(*filters)
        count_statement = count_statement.where(
            *filters,
        )

    statement = (
        statement
        .order_by(
            Incident.detected_at.desc(),
            Incident.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    incidents = list(
        db.scalars(statement).unique().all(),
    )

    total = db.scalar(count_statement) or 0

    return incidents, int(total)

def acquire_incident_deduplication_lock(
    db: Session,
    *,
    lock_id: int,
) -> None:
    """
    Serialize incident correlation for one deduplication key.

    PostgreSQL automatically releases this transaction-level advisory
    lock when the surrounding transaction commits or rolls back.
    """

    db.execute(
        select(
            func.pg_advisory_xact_lock(lock_id),
        )
    ).scalar_one()


def find_suspected_deployment(
    db: Session,
    *,
    service_id: str,
    environment: str,
    detected_at: datetime,
    correlation_window_minutes: int,
) -> Deployment | None:
    """
    Return the latest deployment that can be treated as suspected evidence.

    A deployment is eligible only when it belongs to the incident's
    primary service and environment, occurred no later than detection,
    and falls inside the configured lookback window.

    Returning None is valid and does not prevent incident creation.
    """

    normalised_environment = environment.strip().lower()

    if not normalised_environment:
        return None

    if correlation_window_minutes <= 0:
        raise ValueError(
            "Deployment correlation window must be greater than zero"
        )

    correlation_start = detected_at - timedelta(
        minutes=correlation_window_minutes,
    )

    statement = (
        select(Deployment)
        .join(
            Environment,
            Environment.id == Deployment.environment_id,
        )
        .where(
            Deployment.service_id == service_id,
            Environment.service_id == service_id,
            func.lower(func.trim(Environment.name))
            == normalised_environment,
            Deployment.created_at <= detected_at,
            Deployment.created_at >= correlation_start,
        )
        .order_by(
            Deployment.created_at.desc(),
            Deployment.id.desc(),
        )
        .limit(1)
    )

    return db.execute(statement).scalar_one_or_none()


def get_latest_slo_measurements_for_snapshot(
    db: Session,
    *,
    service_id: str,
    captured_before: datetime,
) -> list[SLOMeasurement]:
    """
    Return the newest known measurement for each SLO metric type.

    Only measurements evaluated on or before incident detection are
    eligible. This keeps the incident snapshot independent of later
    reliability evaluations and current Prometheus values.
    """

    statement = (
        select(SLOMeasurement)
        .where(
            SLOMeasurement.service_id == service_id,
            SLOMeasurement.evaluated_at <= captured_before,
        )
        .order_by(
            SLOMeasurement.evaluated_at.desc(),
            SLOMeasurement.created_at.desc(),
            SLOMeasurement.id.desc(),
        )
    )

    measurements = list(
        db.execute(statement).scalars().all(),
    )

    latest_by_metric: dict[str, SLOMeasurement] = {}

    for measurement in measurements:
        metric_type = measurement.metric_type
        metric_key = str(
            getattr(metric_type, "value", metric_type)
        )

        if metric_key not in latest_by_metric:
            latest_by_metric[metric_key] = measurement

    return list(latest_by_metric.values())


def get_latest_error_budget_status_for_snapshot(
    db: Session,
    *,
    service_id: str,
    slo_definition_id: str,
    captured_before: datetime,
) -> ErrorBudgetStatus | None:
    """
    Return the latest error-budget evaluation known at detection time.
    """

    statement = (
        select(ErrorBudgetStatus)
        .where(
            ErrorBudgetStatus.service_id == service_id,
            ErrorBudgetStatus.slo_definition_id
            == slo_definition_id,
            ErrorBudgetStatus.evaluated_at <= captured_before,
        )
        .order_by(
            ErrorBudgetStatus.evaluated_at.desc(),
            ErrorBudgetStatus.created_at.desc(),
            ErrorBudgetStatus.id.desc(),
        )
        .limit(1)
    )

    return db.execute(statement).scalar_one_or_none()


def find_open_incident_by_deduplication_key(
    db: Session,
    deduplication_key: str,
    *,
    correlation_cutoff: datetime,
) -> Incident | None:
    """
    Find a matching non-terminal incident inside the correlation window.

    Correlation uses the latest linked alert when one exists, falling
    back to the original incident detection timestamp.
    """

    terminal_statuses = (
        IncidentStatus.RESOLVED,
        IncidentStatus.FAILED_RECOVERY,
    )

    latest_alert_at = (
        select(func.max(ReliabilityAlert.created_at))
        .join(
            IncidentAlertLink,
            (
                IncidentAlertLink.reliability_alert_id
                == ReliabilityAlert.id
            ),
        )
        .where(
            IncidentAlertLink.incident_id == Incident.id,
        )
        .correlate(Incident)
        .scalar_subquery()
    )

    latest_correlation_activity = func.coalesce(
        latest_alert_at,
        Incident.detected_at,
    )

    statement = (
        select(Incident)
        .where(
            Incident.deduplication_key == deduplication_key,
            Incident.status.notin_(terminal_statuses),
            Incident.resolved_at.is_(None),
            latest_correlation_activity >= correlation_cutoff,
        )
        .order_by(
            latest_correlation_activity.desc(),
            Incident.detected_at.desc(),
            Incident.created_at.desc(),
        )
        .limit(1)
    )

    return db.execute(statement).scalar_one_or_none()


def get_incident_alerts(
    db: Session,
    incident_id: UUID,
) -> list[ReliabilityAlert]:
    """
    Return all reliability alerts linked to an incident.

    Triggering alerts are returned before non-triggering alerts.
    """

    statement = (
        select(ReliabilityAlert)
        .join(
            IncidentAlertLink,
            (
                IncidentAlertLink.reliability_alert_id
                == ReliabilityAlert.id
            ),
        )
        .where(
            IncidentAlertLink.incident_id == incident_id,
        )
        .order_by(
            IncidentAlertLink.is_triggering_alert.desc(),
            IncidentAlertLink.linked_at.asc(),
        )
    )

    return list(
        db.execute(statement).scalars().all(),
    )


def get_latest_active_assignment(
    db: Session,
    incident_id: UUID,
) -> IncidentAssignment | None:
    """
    Return the latest active assignment for an incident.
    """

    statement = (
        select(IncidentAssignment)
        .where(
            IncidentAssignment.incident_id == incident_id,
            IncidentAssignment.is_active.is_(True),
        )
        .order_by(
            IncidentAssignment.assigned_at.desc(),
            IncidentAssignment.id.desc(),
        )
        .limit(1)
    )

    return db.execute(statement).scalar_one_or_none()


def get_incident_assignments(
    db: Session,
    incident_id: UUID,
) -> list[IncidentAssignment]:
    """
    Return complete assignment history, newest first.
    """

    statement = (
        select(IncidentAssignment)
        .where(
            IncidentAssignment.incident_id == incident_id,
        )
        .order_by(
            IncidentAssignment.assigned_at.desc(),
            IncidentAssignment.id.desc(),
        )
    )

    return list(
        db.execute(statement).scalars().all(),
    )


def get_incident_comments(
    db: Session,
    incident_id: UUID,
) -> list[IncidentComment]:
    """
    Return incident comments in chronological order.
    """

    statement = (
        select(IncidentComment)
        .where(
            IncidentComment.incident_id == incident_id,
        )
        .order_by(
            IncidentComment.created_at.asc(),
            IncidentComment.id.asc(),
        )
    )

    return list(
        db.execute(statement).scalars().all(),
    )


def get_incident_metrics(
    db: Session,
    incident_id: UUID,
) -> list[IncidentMetric]:
    """
    Return captured metric snapshots in deterministic chronological order.
    """

    statement = (
        select(IncidentMetric)
        .where(
            IncidentMetric.incident_id == incident_id,
        )
        .order_by(
            IncidentMetric.captured_at.asc(),
            IncidentMetric.id.asc(),
        )
    )

    return list(
        db.scalars(statement).all(),
    )


def get_incident_timeline(
    db: Session,
    incident_id: UUID,
) -> list[IncidentTimelineEvent]:
    """
    Return the incident timeline in chronological order.
    """

    statement = (
        select(IncidentTimelineEvent)
        .where(
            IncidentTimelineEvent.incident_id == incident_id,
        )
        .order_by(
            IncidentTimelineEvent.occurred_at.asc(),
            IncidentTimelineEvent.id.asc(),
        )
    )

    return list(
        db.execute(statement).scalars().all(),
    )


# ---------------------------------------------------------------------------
# Incident write functions
# ---------------------------------------------------------------------------


def create_incident(
    db: Session,
    *,
    failure_started_at: datetime | None = None,
    **incident_values: Any,
) -> Incident:
    """
    Create and flush an incident without committing the transaction.

    The service layer supplies validated incident fields and owns the
    surrounding commit or rollback. ``failure_started_at`` must contain only
    a reliable source timestamp; when no source timestamp is known, it stays
    ``None``.
    """

    incident = Incident(
        **incident_values,
        failure_started_at=failure_started_at,
    )

    db.add(incident)
    db.flush()

    return incident

def update_incident_status(
    db: Session,
    incident: Incident,
    *,
    status: IncidentStatus,
    **field_updates: Any,
) -> Incident:
    """
    Persist a status update and any service-calculated timestamps or summaries.

    This function deliberately does not validate lifecycle transitions.
    """

    incident.status = status

    for field_name, field_value in field_updates.items():
        setattr(
            incident,
            field_name,
            field_value,
        )

    db.add(incident)
    db.flush()

    return incident


def update_incident(
    db: Session,
    incident: Incident,
    **field_updates,
) -> Incident:
    """Update general incident fields without committing the transaction."""
    protected_fields = {
        "id",
        "incident_number",
        "created_at",
    }

    for field_name, value in field_updates.items():
        if field_name in protected_fields:
            raise ValueError(
                f"Incident field cannot be updated: {field_name}"
            )

        if not hasattr(incident, field_name):
            raise ValueError(
                f"Unknown Incident field: {field_name}"
            )

        setattr(incident, field_name, value)

    db.add(incident)
    db.flush()

    return incident

def update_incident_severity(
    db: Session,
    incident: Incident,
    *,
    severity: IncidentSeverity,
) -> Incident:
    """
    Persist a new incident severity.
    """

    incident.severity = severity

    db.add(incident)
    db.flush()

    return incident


def link_alert_to_incident(
    db: Session,
    *,
    incident_id: UUID,
    reliability_alert_id: str,
    is_triggering_alert: bool = False,
) -> IncidentAlertLink:
    """
    Create an incident-to-alert link.

    Repeated calls return the existing link instead of violating the unique
    incident and reliability-alert constraint.
    """

    existing_statement = select(IncidentAlertLink).where(
        IncidentAlertLink.incident_id == incident_id,
        (
            IncidentAlertLink.reliability_alert_id
            == reliability_alert_id
        ),
    )

    existing_link = db.execute(
        existing_statement,
    ).scalar_one_or_none()

    if existing_link is not None:
        if (
            is_triggering_alert
            and not existing_link.is_triggering_alert
        ):
            existing_link.is_triggering_alert = True
            db.add(existing_link)
            db.flush()

        return existing_link

    alert_link = IncidentAlertLink(
        incident_id=incident_id,
        reliability_alert_id=reliability_alert_id,
        is_triggering_alert=is_triggering_alert,
    )

    db.add(alert_link)
    db.flush()

    return alert_link


def create_assignment(
    db: Session,
    *,
    incident_id: UUID,
    assigned_to_user_id: str,
    assigned_by_user_id: str | None = None,
    assignment_note: str | None = None,
    assigned_at: datetime | None = None,
) -> IncidentAssignment:
    """
    Create an active incident assignment.
    """

    values: dict[str, Any] = {
        "incident_id": incident_id,
        "assigned_to_user_id": assigned_to_user_id,
        "assigned_by_user_id": assigned_by_user_id,
        "assignment_note": assignment_note,
        "is_active": True,
    }

    if assigned_at is not None:
        values["assigned_at"] = assigned_at

    assignment = IncidentAssignment(**values)

    db.add(assignment)
    db.flush()

    return assignment


def close_active_assignment(
    db: Session,
    *,
    incident_id: UUID,
    unassigned_at: datetime,
) -> IncidentAssignment | None:
    """
    Close the latest active assignment for an incident.
    """

    assignment = get_latest_active_assignment(
        db,
        incident_id,
    )

    if assignment is None:
        return None

    assignment.is_active = False
    assignment.unassigned_at = unassigned_at

    db.add(assignment)
    db.flush()

    return assignment


def close_current_assignment(
    db: Session,
    *,
    incident_id: UUID,
    unassigned_at: datetime,
) -> IncidentAssignment | None:
    """Close the current assignment without committing.

    This canonical Sprint 7J name delegates to the existing implementation
    so older service calls using ``close_active_assignment`` remain valid.
    """
    return close_active_assignment(
        db,
        incident_id=incident_id,
        unassigned_at=unassigned_at,
    )


def create_comment(
    db: Session,
    *,
    incident_id: UUID,
    comment: str,
    author_user_id: str | None = None,
    created_at: datetime | None = None,
) -> IncidentComment:
    """
    Create an incident comment.
    """

    incident_comment = IncidentComment(
        id=uuid.uuid4(),
        incident_id=incident_id,
        author_user_id=author_user_id,
        comment=comment,
        created_at=created_at or utc_now(),
    )

    db.add(incident_comment)
    db.flush()

    return incident_comment


def create_timeline_event(
    db: Session,
    *,
    incident_id: UUID,
    event_type: str,
    source: str,
    message: str,
    from_status: IncidentStatus | str | None = None,
    to_status: IncidentStatus | str | None = None,
    actor_user_id: str | None = None,
    alert_id: str | None = None,
    deployment_id: UUID | None = None,
    metadata_json: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> IncidentTimelineEvent:
    """
    Create and flush an immutable incident timeline event.

    Transaction commit or rollback is handled by the service layer.
    """

    timeline_event = IncidentTimelineEvent(
        id=uuid.uuid4(),
        incident_id=incident_id,
        event_type=event_type,
        source=source,
        message=message,
        from_status=_enum_value(from_status),
        to_status=_enum_value(to_status),
        actor_user_id=actor_user_id,
        alert_id=alert_id,
        deployment_id=deployment_id,
        metadata_json=metadata_json or {},
        occurred_at=occurred_at or utc_now(),
    )

    db.add(timeline_event)
    db.flush()

    return timeline_event


def create_metric_snapshot(
    db: Session,
    *,
    incident_id: UUID,
    metric_type: str,
    metric_name: str,
    value: float,
    source: str,
    unit: str | None = None,
    captured_at: datetime | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> IncidentMetric:
    """
    Create one incident metric snapshot.
    """

    values: dict[str, Any] = {
        "incident_id": incident_id,
        "metric_type": metric_type,
        "metric_name": metric_name,
        "value": value,
        "unit": unit,
        "source": source,
        "metadata_json": metadata_json,
    }

    if captured_at is not None:
        values["captured_at"] = captured_at

    metric = IncidentMetric(**values)

    db.add(metric)
    db.flush()

    return metric


def create_audit_event(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_id: str | None = None,
    details: dict[str, Any] | str | None = None,
) -> AuditEvent:
    if isinstance(details, str):
        serialized_details = details
    else:
        serialized_details = json.dumps(
            details or {},
            default=str,
        )

    audit_event = AuditEvent(
        id=str(uuid.uuid4()),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        details=serialized_details,
        created_at=utc_now(),
    )

    db.add(audit_event)
    db.flush()

    return audit_event