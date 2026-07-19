"""Incident application service.

Coordinates incident repositories, pure business rules, timeline creation,
audit logging, and transaction boundaries.
"""

from __future__ import annotations

from statistics import fmean

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from inspect import signature
from types import SimpleNamespace
from typing import Any
from uuid import UUID


from sqlalchemy.orm import Session

from app.incidents import repository, transitions
from app.incidents.config import (
    INCIDENT_CORRELATION_WINDOW_MINUTES,
    INCIDENT_DEPLOYMENT_CORRELATION_WINDOW_MINUTES,
)
from app.incidents.metrics import (
    calculate_incident_metrics,
    format_duration,
)
from app.incidents.rules import (
    build_deduplication_key,
    build_deduplication_lock_id,
    calculate_incident_severity_decision,
    is_more_severe,
)
from app.incidents.schemas import (
    DeploymentSummaryResponse,
    IncidentAcknowledgeRequest,
    IncidentAssignRequest,
    IncidentAssignmentRequest,
    IncidentMetricsSummaryResponse,
    IncidentAssignmentResponse,
    IncidentCalculatedMetricsResponse,
    IncidentCommentCreateRequest,
    IncidentCommentResponse,
    IncidentDetailResponse,
    IncidentListItemResponse,
    IncidentListResponse,
    IncidentMetricResponse,
    IncidentMetricsResponse,
    IncidentStatusUpdateRequest,
    IncidentTimelineEventResponse,
    IncidentTimelineResponse,
    OperatorSummaryResponse,
    ReliabilityAlertSummaryResponse,
    ServiceSummaryResponse,
)
from app.incidents.timeline import (
    INCIDENT_COMMENT_ADDED,
    get_actor_display_name,
    get_timeline_event_type,
)
from app.models import (
    Incident,
    IncidentAssignment,
    IncidentComment,
    IncidentMetric,
    IncidentSeverity,
    IncidentStatus,
    IncidentTimelineEvent,
    ReliabilityAlert,
)


class IncidentNotFoundError(Exception):
    """Raised when an incident identifier does not match a record."""


class IncidentConflictError(Exception):
    """Raised when an incident business rule prevents an operation."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_required_incident(
    db: Session,
    incident_id: UUID,
    *,
    for_update: bool = False,
) -> Incident:
    incident = repository.get_incident_by_id(
        db,
        incident_id,
        for_update=for_update,
    )

    if incident is None:
        raise IncidentNotFoundError(
            "Incident not found"
        )

    return incident


def _request_text(
    request: Any,
    *field_names: str,
) -> str | None:
    """Return the first non-blank text field available on a request."""
    for field_name in field_names:
        value = getattr(request, field_name, None)

        if value is None:
            continue

        normalised = str(value).strip()

        if normalised:
            return normalised

    return None


def _validate_incident_status_transition(
    *,
    current_status: IncidentStatus,
    requested_status: IncidentStatus,
) -> None:
    """Call the canonical transition validator across naming revisions."""
    validator = getattr(
        transitions,
        "validate_incident_transition",
        None,
    )

    if validator is None:
        validator = getattr(
            transitions,
            "validate_status_transition",
            None,
        )

    if validator is None:
        raise RuntimeError(
            "No canonical incident transition validator is available"
        )

    parameter_names = signature(validator).parameters

    if "requested_status" in parameter_names:
        validator(
            current_status=current_status,
            requested_status=requested_status,
        )
        return

    if "new_status" in parameter_names:
        validator(
            current_status=current_status,
            new_status=requested_status,
        )
        return

    validator(current_status, requested_status)


def get_enum_value(value) -> str | None:
    if value is None:
        return None

    return getattr(value, "value", value)


def calculate_average(
    values: list[int],
) -> float | None:
    if not values:
        return None

    return round(fmean(values), 2)


def get_incident_metrics_summary(
    db: Session,
) -> IncidentMetricsSummaryResponse:
    incidents = repository.get_incidents_for_metrics(db)

    mttd_values: list[int] = []
    mtta_values: list[int] = []
    mttr_values: list[int] = []

    open_incident_count = 0
    resolved_incident_count = 0

    severity_counts = {
        "SEV-1": 0,
        "SEV-2": 0,
        "SEV-3": 0,
    }

    for incident in incidents:
        metrics = calculate_incident_metrics(
            failure_started_at=incident.failure_started_at,
            detected_at=incident.detected_at,
            acknowledged_at=incident.acknowledged_at,
            resolved_at=incident.resolved_at,
        )

        if metrics["mttd_seconds"] is not None:
            mttd_values.append(metrics["mttd_seconds"])

        if metrics["mtta_seconds"] is not None:
            mtta_values.append(metrics["mtta_seconds"])

        if metrics["mttr_seconds"] is not None:
            mttr_values.append(metrics["mttr_seconds"])

        status = get_enum_value(incident.status)
        severity = get_enum_value(incident.severity)

        if status == "RESOLVED":
            resolved_incident_count += 1
        else:
            open_incident_count += 1

        if severity in severity_counts:
            severity_counts[severity] += 1

    average_mttd_seconds = calculate_average(mttd_values)
    average_mtta_seconds = calculate_average(mtta_values)
    average_mttr_seconds = calculate_average(mttr_values)

    return IncidentMetricsSummaryResponse(
        average_mttd_seconds=average_mttd_seconds,
        average_mtta_seconds=average_mtta_seconds,
        average_mttr_seconds=average_mttr_seconds,
        average_mttd_display=format_duration(
            average_mttd_seconds
        ),
        average_mtta_display=format_duration(
            average_mtta_seconds
        ),
        average_mttr_display=format_duration(
            average_mttr_seconds
        ),
        open_incident_count=open_incident_count,
        resolved_incident_count=resolved_incident_count,
        sev_1_incident_count=severity_counts["SEV-1"],
        sev_2_incident_count=severity_counts["SEV-2"],
        sev_3_incident_count=severity_counts["SEV-3"],
    )


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _json_details(**values: Any) -> str:
    return json.dumps(
        values,
        default=str,
        sort_keys=True,
    )


def _isoformat_or_none(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _operator_response(user: Any) -> OperatorSummaryResponse | None:
    if user is None:
        return None

    return OperatorSummaryResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
    )


def _service_response(service: Any) -> ServiceSummaryResponse:
    if service is None:
        raise ValueError("Incident primary service could not be loaded")

    return ServiceSummaryResponse(
        id=str(service.id),
        name=service.name,
        service_type=service.service_type,
        owner=service.owner,
    )


def _alert_response(
    alert: ReliabilityAlert | None,
) -> ReliabilityAlertSummaryResponse | None:
    if alert is None:
        return None

    return ReliabilityAlertSummaryResponse(
        id=str(alert.id),
        service_id=str(alert.service_id),
        slo_definition_id=str(alert.slo_definition_id),
        alert_type=_enum_value(alert.alert_type),
        severity=_enum_value(alert.severity),
        triggered_value=float(alert.triggered_value),
        threshold_value=float(alert.threshold_value),
        deployment_id=alert.deployment_id,
        status=_enum_value(alert.status),
        created_at=alert.created_at,
        resolved_at=alert.resolved_at,
    )


def _deployment_response(
    deployment: Any,
) -> DeploymentSummaryResponse | None:
    if deployment is None:
        return None

    return DeploymentSummaryResponse(
        id=deployment.id,
        service_id=str(deployment.service_id),
        service_name=deployment.service_name,
        environment_id=deployment.environment_id,
        image_tag=deployment.image_tag,
        deployment_version=deployment.deployment_version,
        commit_sha=deployment.commit_sha,
        argo_sync_status=deployment.argo_sync_status,
        kubernetes_rollout_status=(deployment.kubernetes_rollout_status),
        deployed_at=deployment.deployed_at,
        created_at=deployment.created_at,
    )


def _assignment_response(
    assignment: IncidentAssignment | None,
) -> IncidentAssignmentResponse | None:
    if assignment is None:
        return None

    return IncidentAssignmentResponse(
        id=assignment.id,
        incident_id=assignment.incident_id,
        assigned_to_user_id=assignment.assigned_to_user_id,
        assigned_to_user=_operator_response(assignment.assigned_to_user),
        assigned_by_user_id=assignment.assigned_by_user_id,
        assigned_by_user=_operator_response(assignment.assigned_by_user),
        assignment_note=assignment.assignment_note,
        assigned_at=assignment.assigned_at,
        unassigned_at=assignment.unassigned_at,
        is_active=assignment.is_active,
    )


def _comment_response(
    comment: IncidentComment,
) -> IncidentCommentResponse:
    return IncidentCommentResponse(
        id=comment.id,
        incident_id=comment.incident_id,
        author_user_id=comment.author_user_id,
        author=_operator_response(comment.author),
        comment=comment.comment,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


def _metric_response(
    metric: IncidentMetric,
) -> IncidentMetricResponse:
    return IncidentMetricResponse(
        id=metric.id,
        incident_id=metric.incident_id,
        metric_type=metric.metric_type,
        metric_name=metric.metric_name,
        value=float(metric.value),
        unit=metric.unit,
        source=metric.source,
        captured_at=metric.captured_at,
        metadata_json=metric.metadata_json,
        created_at=metric.created_at,
    )


def _timeline_event_response(
    event: IncidentTimelineEvent,
) -> IncidentTimelineEventResponse:
    return IncidentTimelineEventResponse(
        id=event.id,
        incident_id=event.incident_id,
        event_type=event.event_type,
        source=event.source,
        message=event.message,
        from_status=event.from_status,
        to_status=event.to_status,
        actor_user_id=event.actor_user_id,
        actor=_operator_response(event.actor_user),
        alert_id=event.alert_id,
        alert=_alert_response(event.alert),
        deployment_id=event.deployment_id,
        deployment=_deployment_response(event.deployment),
        metadata_json=event.metadata_json,
        occurred_at=event.occurred_at,
        created_at=event.created_at,
    )


def _incident_metrics_values(
    incident: Incident,
) -> dict[str, int | str | None]:
    return calculate_incident_metrics(
        failure_started_at=incident.failure_started_at,
        detected_at=incident.detected_at,
        acknowledged_at=incident.acknowledged_at,
        resolved_at=incident.resolved_at,
    )


def _calculated_metrics_response(
    incident: Incident,
) -> IncidentCalculatedMetricsResponse:
    """Build the legacy nested metrics object for API compatibility."""
    metrics = _incident_metrics_values(incident)

    return IncidentCalculatedMetricsResponse(
        incident_id=incident.id,
        failure_started_at=incident.failure_started_at,
        detected_at=incident.detected_at,
        acknowledged_at=incident.acknowledged_at,
        resolved_at=incident.resolved_at,
        mttd_seconds=metrics["mttd_seconds"],
        mtta_seconds=metrics["mtta_seconds"],
        mttr_seconds=metrics["mttr_seconds"],
    )


def build_incident_list_item_response(
    incident: Incident,
) -> IncidentListItemResponse:
    """Build one incident list item with calculated duration fields."""
    service_id = incident.primary_service_id or incident.service_id

    if not service_id:
        raise ValueError(
            f"Incident {incident.id} has no primary service"
        )

    response = IncidentListItemResponse(
        incident_id=incident.id,
        id=incident.id,
        incident_number=incident.incident_number,
        title=incident.title,
        severity=incident.severity,
        status=incident.status,
        service_id=str(service_id),
        service_name=(
            incident.primary_service.name
            if incident.primary_service is not None
            else None
        ),
        environment=incident.environment,
        assigned_operator=_operator_response(
            incident.current_assignee
        ),
        suspected_deployment_id=(
            incident.suspected_deployment_id
        ),
        failure_started_at=incident.failure_started_at,
        detected_at=incident.detected_at,
        acknowledged_at=incident.acknowledged_at,
        resolved_at=incident.resolved_at,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )

    return response.model_copy(
        update=_incident_metrics_values(incident),
    )

def _affected_services(
    incident: Incident,
    alerts: list[ReliabilityAlert],
) -> list[ServiceSummaryResponse]:
    services: dict[str, Any] = {}

    if incident.primary_service is not None:
        services[str(incident.primary_service.id)] = incident.primary_service

    for alert in alerts:
        if alert.service is not None:
            services[str(alert.service.id)] = alert.service

    return [_service_response(service) for service in services.values()]


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
    page: int = 1,
    page_size: int = 25,
) -> IncidentListResponse:
    if page < 1:
        raise ValueError(
            "page must be greater than or equal to 1"
        )

    if page_size < 1:
        raise ValueError(
            "page_size must be greater than or equal to 1"
        )

    if (
        from_date is not None
        and to_date is not None
        and from_date > to_date
    ):
        raise ValueError(
            "from_date cannot be later than to_date"
        )

    offset = (page - 1) * page_size

    incidents, total = repository.list_incidents(
        db,
        status=(
            status.value
            if hasattr(status, "value")
            else status
        ),
        severity=(
            severity.value
            if hasattr(severity, "value")
            else severity
        ),
        service_id=service_id,
        environment=environment,
        assignee_id=assignee_id,
        from_date=from_date,
        to_date=to_date,
        offset=offset,
        limit=page_size,
    )

    items = [
        build_incident_list_item_response(incident)
        for incident in incidents
    ]

    return IncidentListResponse.create(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )

def _metric_unit(
    metric_name: str,
) -> str | None:
    units = {
        "AVAILABILITY": "%",
        "ERROR_RATE": "%",
        "P95_LATENCY": "ms",
        "LATENCY": "ms",
    }

    return units.get(metric_name.upper())


def _capture_initial_reliability_snapshot(
    db: Session,
    *,
    incident: Incident,
    alert: ReliabilityAlert,
    detected_at: datetime,
) -> None:
    """
    Persist the reliability state known when the incident was detected.

    These records are independent of later Prometheus queries and later
    SLO or error-budget evaluations.
    """

    measurements = (
        repository.get_latest_slo_measurements_for_snapshot(
            db,
            service_id=str(incident.primary_service_id),
            captured_before=detected_at,
        )
    )

    for measurement in measurements:
        metric_name = str(
            _enum_value(measurement.metric_type)
        )

        repository.create_metric_snapshot(
            db,
            incident_id=incident.id,
            metric_type="SLO_MEASUREMENT",
            metric_name=metric_name,
            value=float(measurement.measured_value),
            unit=_metric_unit(metric_name),
            source=measurement.source or "UNKNOWN",
            captured_at=measurement.evaluated_at,
            metadata_json={
                "snapshot_reason": "incident_detection",
                "measurement_id": str(measurement.id),
                "slo_definition_id": str(
                    measurement.slo_definition_id
                ),
                "service_id": str(measurement.service_id),
                "target_value": float(
                    measurement.target_value
                ),
                "is_breached": bool(
                    measurement.is_breached
                ),
                "window_minutes": int(
                    measurement.window_minutes
                ),
                "evaluated_at": _isoformat_or_none(
                    measurement.evaluated_at
                ),
            },
        )

    if alert.slo_definition_id is None:
        return

    error_budget = (
        repository.get_latest_error_budget_status_for_snapshot(
            db,
            service_id=str(incident.primary_service_id),
            slo_definition_id=str(
                alert.slo_definition_id
            ),
            captured_before=detected_at,
        )
    )

    if error_budget is None:
        return

    repository.create_metric_snapshot(
        db,
        incident_id=incident.id,
        metric_type="ERROR_BUDGET",
        metric_name="remaining_percentage",
        value=float(error_budget.remaining_percentage),
        unit="%",
        source="SLO_ENGINE",
        captured_at=error_budget.evaluated_at,
        metadata_json={
            "snapshot_reason": "incident_detection",
            "error_budget_status_id": str(
                error_budget.id
            ),
            "slo_definition_id": str(
                error_budget.slo_definition_id
            ),
            "service_id": str(
                error_budget.service_id
            ),
            "status": str(
                _enum_value(error_budget.status)
            ),
            "target_percentage": float(
                error_budget.target_percentage
            ),
            "allowed_failure_percentage": float(
                error_budget.allowed_failure_percentage
            ),
            "consumed_percentage": float(
                error_budget.consumed_percentage
            ),
            "remaining_percentage": float(
                error_budget.remaining_percentage
            ),
            "burn_rate": float(
                error_budget.burn_rate
            ),
            "window_minutes": int(
                error_budget.window_minutes
            ),
            "evaluated_at": _isoformat_or_none(
                error_budget.evaluated_at
            ),
        },
    )


def build_incident_detail_response(
    incident: Incident,
    *,
    alerts: list[ReliabilityAlert],
    current_assignment: IncidentAssignment | None,
    assignments: list[IncidentAssignment],
    comments: list[IncidentComment],
    metric_snapshot: list[IncidentMetric],
    timeline_events: list[IncidentTimelineEvent],
) -> IncidentDetailResponse:
    """Build the complete detail payload and calculated metrics."""
    timeline_responses = [
        _timeline_event_response(event)
        for event in timeline_events
    ]

    payload: dict[str, Any] = {
        "incident": build_incident_list_item_response(incident),
        "description": incident.description,
        "deduplication_key": incident.deduplication_key or "",
        "primary_service": _service_response(
            incident.primary_service
        ),
        "affected_services": _affected_services(
            incident,
            alerts,
        ),
        "triggering_alert_id": incident.triggering_alert_id,
        "triggering_alert": _alert_response(
            incident.triggering_alert
        ),
        "related_alerts": [
            response
            for alert in alerts
            if (response := _alert_response(alert)) is not None
        ],
        "suspected_deployment": _deployment_response(
            incident.suspected_deployment
        ),
        "failure_started_at": incident.failure_started_at,
        "investigation_started_at": (
            incident.investigation_started_at
        ),
        "remediation_started_at": (
            incident.remediation_started_at
        ),
        "created_by": incident.created_by,
        "creator": _operator_response(incident.creator),
        "current_assignment": _assignment_response(
            current_assignment
        ),
        "assignment_history": [
            response
            for assignment in assignments
            if (response := _assignment_response(assignment))
            is not None
        ],
        "comments": [
            _comment_response(comment)
            for comment in comments
        ],
        "metric_snapshot": [
            _metric_response(metric)
            for metric in metric_snapshot
        ],
        "resolution_summary": incident.resolution_summary,
        "remediation_summary": incident.remediation_summary,
        "calculated_incident_metrics": (
            _calculated_metrics_response(incident)
        ),
    }

    # Support the newer Sprint 7J names while retaining the existing fields
    # until the frontend and older clients have migrated.
    model_fields = IncidentDetailResponse.model_fields

    if "timeline_summary" in model_fields:
        payload["timeline_summary"] = timeline_responses

    if "latest_timeline_events" in model_fields:
        payload["latest_timeline_events"] = (
            timeline_responses[-10:]
        )

    if "rca_summary" in model_fields:
        payload["rca_summary"] = incident.rca_summary

    if "root_cause_analysis" in model_fields:
        payload["root_cause_analysis"] = incident.rca_summary

    response = IncidentDetailResponse(**payload)

    return response.model_copy(
        update=_incident_metrics_values(incident),
    )

def get_incident_detail(
    db: Session,
    incident_id: UUID,
) -> IncidentDetailResponse:
    incident = _get_required_incident(
        db,
        incident_id,
    )

    alerts = repository.get_incident_alerts(
        db,
        incident.id,
    )
    current_assignment = repository.get_latest_active_assignment(
        db,
        incident.id,
    )
    assignments = repository.get_incident_assignments(
        db,
        incident.id,
    )
    comments = repository.get_incident_comments(
        db,
        incident.id,
    )
    metrics = repository.get_incident_metrics(
        db,
        incident.id,
    )
    timeline_events = repository.get_incident_timeline(
        db,
        incident.id,
    )

    return build_incident_detail_response(
        incident,
        alerts=alerts,
        current_assignment=current_assignment,
        assignments=assignments,
        comments=comments,
        metric_snapshot=metrics,
        timeline_events=timeline_events,
    )

def get_incident_timeline(
    db: Session,
    incident_id: UUID,
) -> IncidentTimelineResponse:
    incident = _get_required_incident(
        db,
        incident_id,
    )

    events = repository.get_incident_timeline(
        db,
        incident.id,
    )

    return IncidentTimelineResponse(
        incident_id=incident.id,
        events=[
            _timeline_event_response(event)
            for event in events
        ],
    )

def _latest_metric_value(
    snapshots: list[IncidentMetric],
    *,
    metric_name: str,
) -> float | None:
    for snapshot in reversed(snapshots):
        if str(snapshot.metric_name).lower() == metric_name.lower():
            return float(snapshot.value)

    return None


def _latest_error_budget_status(
    snapshots: list[IncidentMetric],
) -> str | None:
    for snapshot in reversed(snapshots):
        if str(snapshot.metric_type).upper() != "ERROR_BUDGET":
            continue

        metadata = snapshot.metadata_json or {}
        status = metadata.get("status")

        if status is not None:
            return str(status)

    return None


def get_incident_metrics(
    db: Session,
    incident_id: UUID,
) -> IncidentMetricsResponse:
    incident = _get_required_incident(
        db,
        incident_id,
    )

    snapshots = repository.get_incident_metrics(
        db,
        incident.id,
    )

    calculated = calculate_incident_metrics(
        failure_started_at=incident.failure_started_at,
        detected_at=incident.detected_at,
        acknowledged_at=incident.acknowledged_at,
        resolved_at=incident.resolved_at,
    )

    return IncidentMetricsResponse(
        incident_id=incident.id,
        metric_snapshot=[
            _metric_response(snapshot)
            for snapshot in snapshots
        ],
        **calculated,
        alert_threshold=_latest_metric_value(
            snapshots,
            metric_name="threshold_value",
        ),
        triggered_value=_latest_metric_value(
            snapshots,
            metric_name="triggered_value",
        ),
        error_budget_status=_latest_error_budget_status(
            snapshots
        ),
    )

def create_or_update_incident_from_alert(
    db: Session,
    alert: ReliabilityAlert,
    *,
    environment: str,
    failure_started_at: datetime | None = None,
    affected_service_count: int = 1,
    availability_percent: float | None = None,
    high_severity_alert_count: int = 0,
    actor_user_id: str | None = None,
) -> IncidentDetailResponse:
    """
    Create or update an open incident for a reliability alert.

    ReliabilityAlert has no environment column, so callers must supply
    the environment from the event or telemetry context.

    Automatic timeline and audit records are attributed to the system.
    The actor_user_id argument is retained for backwards compatibility and
    may still be used as the incident creator when explicitly supplied.
    """
    try:
        existing_alert_link = (
            repository.get_incident_alert_link_by_alert_id(
                db,
                str(alert.id),
            )
        )

        # Kafka delivery is at-least-once. If this alert was already linked,
        # return the existing incident without creating duplicate timeline,
        # audit, metric, or correlation records.
        if existing_alert_link is not None:
            existing_detail = get_incident_detail(
                db,
                existing_alert_link.incident_id,
            )

            if existing_detail is None:
                raise RuntimeError(
                    "Incident alert link references a missing "
                    f"incident: alert_id={alert.id}"
                )

            return existing_detail

        normalised_environment = environment.strip()

        if not normalised_environment:
            raise ValueError("Incident environment must not be empty")

        if availability_percent is None:
            alert_type = _enum_value(alert.alert_type)

            if alert_type == "AVAILABILITY_BREACH":
                availability_percent = float(alert.triggered_value)

        deduplication_category = (
            alert.slo_definition_id
            or _enum_value(alert.alert_type)
        )

        deduplication_key = build_deduplication_key(
            alert.service_id,
            normalised_environment,
            deduplication_category,
        )

        deduplication_lock_id = build_deduplication_lock_id(
            deduplication_key,
        )
        repository.acquire_incident_deduplication_lock(
            db,
            lock_id=deduplication_lock_id,
        )

        alert_type_value = _enum_value(alert.alert_type)
        alert_severity_value = _enum_value(alert.severity)
        alert_created_at = alert.created_at or _utcnow()

        if alert_created_at.tzinfo is None:
            alert_created_at = alert_created_at.replace(
                tzinfo=timezone.utc,
            )

        suspected_deployment = repository.find_suspected_deployment(
            db,
            service_id=alert.service_id,
            environment=normalised_environment,
            detected_at=alert_created_at,
            correlation_window_minutes=(
                INCIDENT_DEPLOYMENT_CORRELATION_WINDOW_MINUTES
            ),
        )

        severity_decision = calculate_incident_severity_decision(
            alert.severity,
            environment=normalised_environment,
            alert_type=alert.alert_type,
            service_criticality=getattr(
                alert.service,
                "criticality",
                None,
            ),
            measured_value=float(alert.triggered_value),
            threshold_value=float(alert.threshold_value),
            availability_percent=availability_percent,
            affected_service_count=affected_service_count,
            high_severity_alert_count=high_severity_alert_count,
            deployment_correlated=(
                suspected_deployment is not None
            ),
            error_budget_exhausted=(
                alert_type_value == "ERROR_BUDGET_EXHAUSTED"
            ),
        )
        severity = severity_decision.severity

        correlation_cutoff = alert_created_at - timedelta(
            minutes=INCIDENT_CORRELATION_WINDOW_MINUTES,
        )

        incident = repository.find_open_incident_by_deduplication_key(
            db,
            deduplication_key,
            correlation_cutoff=correlation_cutoff,
        )
        incident_was_created = incident is None
        should_capture_alert_metrics = True

        if incident_was_created:
            service_name = (
                alert.service.name
                if alert.service is not None
                else str(alert.service_id)
            )
            alert_name = str(alert_type_value).replace(
                "_",
                " ",
            ).title()

            detected_at = alert_created_at
            failure_time = failure_started_at or detected_at

            incident = repository.create_incident(
                db,
                title=f"{alert_name}: {service_name}",
                description=(
                    "Automatically created from reliability "
                    f"alert {alert.id}."
                ),
                severity=severity,
                status=IncidentStatus.DETECTED,
                primary_service_id=alert.service_id,
                environment=normalised_environment,
                triggering_alert_id=alert.id,
                suspected_deployment_id=(
                    suspected_deployment.id
                    if suspected_deployment is not None
                    else None
                ),
                deduplication_key=deduplication_key,
                failure_started_at=failure_time,
                detected_at=detected_at,
                created_by=actor_user_id,
                service_id=alert.service_id,
                correlation_id=deduplication_key,
                triggered_by_event_id=alert.id,
            )

            alert_link = repository.link_alert_to_incident(
                db,
                incident_id=incident.id,
                reliability_alert_id=alert.id,
                is_triggering_alert=True,
            )
            alert_linked_at = (
                getattr(alert_link, "linked_at", None)
                or getattr(alert_link, "created_at", None)
                or _utcnow()
            )
            incident_created_at = (
                incident.detected_at
                or incident.created_at
                or detected_at
            )

            repository.create_timeline_event(
                db,
                incident_id=incident.id,
                event_type="RELIABILITY_ALERT_CREATED",
                source="RELIABILITY",
                message=(
                    f"Reliability alert {alert.id} generated: "
                    f"{alert_type_value}"
                ),
                actor_user_id=None,
                alert_id=alert.id,
                metadata_json={
                    "alert_type": alert_type_value,
                    "alert_severity": alert_severity_value,
                },
                occurred_at=alert_created_at,
            )

            repository.create_timeline_event(
                db,
                incident_id=incident.id,
                event_type="INCIDENT_CREATED",
                source="SYSTEM",
                message=(
                    f"Incident {incident.incident_number} "
                    "automatically created"
                ),
                to_status=IncidentStatus.DETECTED,
                actor_user_id=None,
                alert_id=alert.id,
                metadata_json={
                    "deduplication_key": deduplication_key,
                    "incident_severity": severity.value,
                    "severity_reason_code": (
                        severity_decision.reason_code
                    ),
                    "severity_explanation": (
                        severity_decision.explanation
                    ),
                    "severity_evidence": severity_decision.evidence,
                },
                occurred_at=incident_created_at,
            )

            # This event is emitted only after a new IncidentAlertLink is
            # inserted. Duplicate Kafka delivery returns near the start of
            # this function and therefore cannot emit it again.
            repository.create_timeline_event(
                db,
                incident_id=incident.id,
                event_type="ALERT_ATTACHED",
                source="RELIABILITY",
                message=(
                    f"Reliability alert {alert.id} attached "
                    "as the triggering alert."
                ),
                actor_user_id=None,
                alert_id=alert.id,
                deployment_id=alert.deployment_id,
                metadata_json={
                    "is_triggering_alert": True,
                    "alert_type": alert_type_value,
                    "alert_severity": alert_severity_value,
                    "incident_alert_link_id": (
                        str(alert_link.id)
                        if getattr(alert_link, "id", None) is not None
                        else None
                    ),
                },
                occurred_at=alert_linked_at,
            )

            if suspected_deployment is not None:
                deployment_label = (
                    suspected_deployment.deployment_version
                    or suspected_deployment.image_tag
                    or str(suspected_deployment.id)
                )
                deployment_released_at = (
                    suspected_deployment.deployed_at
                    or suspected_deployment.created_at
                    or detected_at
                )
                correlation_time = _utcnow()

                repository.create_timeline_event(
                    db,
                    incident_id=incident.id,
                    event_type="DEPLOYMENT_RELEASED",
                    source="DEPLOYMENT",
                    message=(
                        f"Deployment {deployment_label} released "
                        f"to {normalised_environment}."
                    ),
                    actor_user_id=None,
                    deployment_id=suspected_deployment.id,
                    metadata_json={
                        "service_id": str(alert.service_id),
                        "environment": normalised_environment,
                        "deployment_id": str(
                            suspected_deployment.id
                        ),
                        "deployment_version": (
                            suspected_deployment.deployment_version
                        ),
                        "image_tag": suspected_deployment.image_tag,
                    },
                    occurred_at=deployment_released_at,
                )

                repository.create_timeline_event(
                    db,
                    incident_id=incident.id,
                    event_type="DEPLOYMENT_CORRELATED",
                    source="DEPLOYMENT_CORRELATION",
                    message=(
                        f"Suspected deployment {deployment_label} "
                        f"was the latest matching "
                        f"{normalised_environment} deployment "
                        "before incident detection."
                    ),
                    actor_user_id=None,
                    alert_id=alert.id,
                    deployment_id=suspected_deployment.id,
                    metadata_json={
                        "classification": "suspected_deployment",
                        "service_id": str(alert.service_id),
                        "environment": normalised_environment,
                        "deployment_id": str(
                            suspected_deployment.id
                        ),
                        "deployment_created_at": (
                            _isoformat_or_none(
                                suspected_deployment.created_at
                            )
                        ),
                        "deployment_released_at": (
                            _isoformat_or_none(
                                suspected_deployment.deployed_at
                            )
                        ),
                        "incident_detected_at": (
                            _isoformat_or_none(detected_at)
                        ),
                        "correlation_window_minutes": (
                            INCIDENT_DEPLOYMENT_CORRELATION_WINDOW_MINUTES
                        ),
                    },
                    occurred_at=correlation_time,
                )

                repository.create_audit_event(
                    db,
                    action="INCIDENT_DEPLOYMENT_CORRELATED",
                    entity_type="INCIDENT",
                    entity_id=str(incident.id),
                    actor_id=None,
                    details={
                        "actor_type": "SYSTEM",
                        "source": "telemetry_alert_consumer",
                        "classification": "suspected_deployment",
                        "alert_id": str(alert.id),
                        "deployment_id": str(
                            suspected_deployment.id
                        ),
                        "service_id": str(alert.service_id),
                        "environment": normalised_environment,
                        "deployment_created_at": (
                            _isoformat_or_none(
                                suspected_deployment.created_at
                            )
                        ),
                        "deployment_released_at": (
                            _isoformat_or_none(
                                suspected_deployment.deployed_at
                            )
                        ),
                        "incident_detected_at": (
                            _isoformat_or_none(detected_at)
                        ),
                        "correlated_at": (
                            _isoformat_or_none(correlation_time)
                        ),
                        "correlation_window_minutes": (
                            INCIDENT_DEPLOYMENT_CORRELATION_WINDOW_MINUTES
                        ),
                    },
                )

            repository.create_audit_event(
                db,
                action="INCIDENT_CREATED",
                entity_type="INCIDENT",
                entity_id=str(incident.id),
                actor_id=None,
                details={
                    "actor_type": "SYSTEM",
                    "source": "telemetry_alert_consumer",
                    "alert_id": str(alert.id),
                    "service_id": str(alert.service_id),
                    "environment": normalised_environment,
                    "severity": severity.value,
                    "severity_reason_code": (
                        severity_decision.reason_code
                    ),
                    "severity_explanation": (
                        severity_decision.explanation
                    ),
                    "severity_evidence": severity_decision.evidence,
                    "deduplication_key": deduplication_key,
                },
            )
        else:
            linked_alerts = repository.get_incident_alerts(
                db,
                incident.id,
            )
            linked_alert_ids = {
                str(linked_alert.id)
                for linked_alert in linked_alerts
            }
            should_capture_alert_metrics = (
                str(alert.id) not in linked_alert_ids
            )

            if should_capture_alert_metrics:
                alert_link = repository.link_alert_to_incident(
                    db,
                    incident_id=incident.id,
                    reliability_alert_id=alert.id,
                    is_triggering_alert=False,
                )
                alert_linked_at = (
                    getattr(alert_link, "linked_at", None)
                    or getattr(alert_link, "created_at", None)
                    or _utcnow()
                )

                repository.create_timeline_event(
                    db,
                    incident_id=incident.id,
                    event_type="RELIABILITY_ALERT_CREATED",
                    source="RELIABILITY",
                    message=(
                        f"Reliability alert {alert.id} generated: "
                        f"{alert_type_value}"
                    ),
                    actor_user_id=None,
                    alert_id=alert.id,
                    metadata_json={
                        "alert_type": alert_type_value,
                        "alert_severity": alert_severity_value,
                    },
                    occurred_at=alert_created_at,
                )

                # Emit ALERT_ATTACHED only when the repository call above
                # inserted a new IncidentAlertLink.
                repository.create_timeline_event(
                    db,
                    incident_id=incident.id,
                    event_type="ALERT_ATTACHED",
                    source="RELIABILITY",
                    message=(
                        f"Reliability alert {alert.id} attached "
                        "to the existing incident."
                    ),
                    actor_user_id=None,
                    alert_id=alert.id,
                    deployment_id=alert.deployment_id,
                    metadata_json={
                        "is_triggering_alert": False,
                        "alert_type": alert_type_value,
                        "alert_severity": alert_severity_value,
                        "incident_alert_link_id": (
                            str(alert_link.id)
                            if getattr(alert_link, "id", None) is not None
                            else None
                        ),
                    },
                    occurred_at=alert_linked_at,
                )

                repository.create_audit_event(
                    db,
                    action="INCIDENT_ALERT_ATTACHED",
                    entity_type="INCIDENT",
                    entity_id=str(incident.id),
                    actor_id=None,
                    details={
                        "actor_type": "SYSTEM",
                        "source": "telemetry_alert_consumer",
                        "alert_id": str(alert.id),
                        "is_triggering_alert": False,
                        "linked_at": (
                            _isoformat_or_none(alert_linked_at)
                        ),
                    },
                )

            if is_more_severe(
                severity,
                incident.severity,
            ):
                previous_severity = incident.severity
                escalation_time = _utcnow()

                repository.update_incident_severity(
                    db,
                    incident,
                    severity=severity,
                )

                repository.create_timeline_event(
                    db,
                    incident_id=incident.id,
                    event_type="SEVERITY_CHANGED",
                    source="RELIABILITY",
                    message=(
                        "Incident severity escalated from "
                        f"{previous_severity.value} to "
                        f"{severity.value}."
                    ),
                    actor_user_id=None,
                    alert_id=alert.id,
                    deployment_id=alert.deployment_id,
                    metadata_json={
                        "previous_severity": (
                            previous_severity.value
                        ),
                        "new_severity": severity.value,
                        "reason_code": severity_decision.reason_code,
                        "explanation": severity_decision.explanation,
                        "evidence": severity_decision.evidence,
                    },
                    occurred_at=escalation_time,
                )

                repository.create_audit_event(
                    db,
                    action="INCIDENT_SEVERITY_CHANGED",
                    entity_type="INCIDENT",
                    entity_id=str(incident.id),
                    actor_id=None,
                    details={
                        "actor_type": "SYSTEM",
                        "source": "telemetry_alert_consumer",
                        "previous_severity": (
                            previous_severity.value
                        ),
                        "new_severity": severity.value,
                        "reason_code": severity_decision.reason_code,
                        "explanation": severity_decision.explanation,
                        "evidence": severity_decision.evidence,
                        "alert_id": str(alert.id),
                        "escalated_at": (
                            _isoformat_or_none(escalation_time)
                        ),
                    },
                )

        if should_capture_alert_metrics:
            repository.create_metric_snapshot(
                db,
                incident_id=incident.id,
                metric_type="RELIABILITY_ALERT",
                metric_name="triggered_value",
                value=float(alert.triggered_value),
                source="RELIABILITY_ALERT",
                captured_at=alert_created_at,
                metadata_json={
                    "snapshot_reason": "alert_linked",
                    "alert_id": str(alert.id),
                    "alert_type": alert_type_value,
                    "slo_definition_id": (
                        str(alert.slo_definition_id)
                        if alert.slo_definition_id is not None
                        else None
                    ),
                    "evaluated_at": (
                        _isoformat_or_none(alert_created_at)
                    ),
                },
            )

            repository.create_metric_snapshot(
                db,
                incident_id=incident.id,
                metric_type="RELIABILITY_ALERT",
                metric_name="threshold_value",
                value=float(alert.threshold_value),
                source="RELIABILITY_ALERT",
                captured_at=alert_created_at,
                metadata_json={
                    "snapshot_reason": "alert_linked",
                    "alert_id": str(alert.id),
                    "alert_type": alert_type_value,
                    "slo_definition_id": (
                        str(alert.slo_definition_id)
                        if alert.slo_definition_id is not None
                        else None
                    ),
                    "evaluated_at": (
                        _isoformat_or_none(alert_created_at)
                    ),
                },
            )

        if incident_was_created:
            _capture_initial_reliability_snapshot(
                db,
                incident=incident,
                alert=alert,
                detected_at=incident.detected_at,
            )

        db.commit()
        db.refresh(incident)

        detail = get_incident_detail(
            db,
            incident.id,
        )

        if detail is None:
            raise RuntimeError(
                "Incident was committed but could not be reloaded"
            )

        return detail

    except Exception:
        db.rollback()
        raise


def _lifecycle_timestamp_updates(
    incident: Incident,
    *,
    requested_status: IncidentStatus,
    changed_at: datetime,
) -> dict[str, Any]:
    """Return lifecycle timestamp updates for one validated transition.

    Investigation and remediation timestamps record when those phases first
    started, so retries after failed recovery must not overwrite them.
    """
    updates: dict[str, Any] = {}

    if requested_status == IncidentStatus.ACKNOWLEDGED:
        updates["acknowledged_at"] = (
            incident.acknowledged_at
            or changed_at
        )

    elif requested_status == IncidentStatus.INVESTIGATING:
        updates["investigation_started_at"] = (
            incident.investigation_started_at
            or changed_at
        )

    elif requested_status == IncidentStatus.REMEDIATING:
        updates["remediation_started_at"] = (
            incident.remediation_started_at
            or changed_at
        )

    elif requested_status == IncidentStatus.RESOLVED:
        updates["resolved_at"] = changed_at

    elif requested_status == IncidentStatus.FAILED_RECOVERY:
        updates["resolved_at"] = None

    return updates


def _stage_status_update(
    db: Session,
    incident: Incident,
    request: IncidentStatusUpdateRequest | Any,
    *,
    actor_user_id: str | None,
    occurred_at: datetime,
    timeline_metadata: dict[str, Any] | None = None,
    audit_metadata: dict[str, Any] | None = None,
) -> Incident:
    """Stage one validated status transition without committing.

    Every successful call creates exactly one timeline event and exactly one
    audit event. The caller owns the transaction commit or rollback.
    """
    previous_status = IncidentStatus(
        _enum_value(incident.status)
    )
    requested_status = IncidentStatus(
        _enum_value(request.status)
    )

    try:
        _validate_incident_status_transition(
            current_status=previous_status,
            requested_status=requested_status,
        )
    except IncidentConflictError:
        raise
    except ValueError as exc:
        raise IncidentConflictError(str(exc)) from exc

    reason = _request_text(
        request,
        "reason",
        "note",
    )
    resolution_summary = _request_text(
        request,
        "resolution_summary",
    )
    rca_summary = _request_text(
        request,
        "rca_summary",
        "root_cause_analysis",
    )
    remediation_summary = _request_text(
        request,
        "remediation_summary",
    )

    field_updates = _lifecycle_timestamp_updates(
        incident,
        requested_status=requested_status,
        changed_at=occurred_at,
    )

    if requested_status == IncidentStatus.RESOLVED:
        # Sprint 7J uses a required reason. Older clients may still send a
        # dedicated resolution_summary, so support both during migration.
        resolution_summary = resolution_summary or reason

        if not resolution_summary:
            raise IncidentConflictError(
                "A resolution reason is required when resolving "
                "an incident"
            )

        field_updates["resolution_summary"] = (
            resolution_summary
        )
    elif resolution_summary is not None:
        field_updates["resolution_summary"] = (
            resolution_summary
        )

    if rca_summary is not None:
        field_updates["rca_summary"] = rca_summary

    if remediation_summary is not None:
        field_updates["remediation_summary"] = (
            remediation_summary
        )

    repository.update_incident_status(
        db,
        incident,
        status=requested_status,
        **field_updates,
    )

    default_message = (
        "Incident status changed from "
        f"{previous_status.value} to "
        f"{requested_status.value}."
    )

    if (
        requested_status == IncidentStatus.RESOLVED
        and resolution_summary
    ):
        default_message = resolution_summary

    repository.create_timeline_event(
        db,
        incident_id=incident.id,
        event_type=get_timeline_event_type(
            requested_status
        ),
        source=(
            "OPERATOR"
            if actor_user_id is not None
            else "SYSTEM"
        ),
        message=reason or default_message,
        from_status=previous_status.value,
        to_status=requested_status.value,
        actor_user_id=actor_user_id,
        metadata_json=timeline_metadata or {},
        occurred_at=occurred_at,
    )

    audit_action = (
        "INCIDENT_ACKNOWLEDGED"
        if requested_status == IncidentStatus.ACKNOWLEDGED
        else "INCIDENT_STATUS_CHANGED"
    )

    request_path = (
        f"/api/incidents/{incident.id}/acknowledge"
        if requested_status == IncidentStatus.ACKNOWLEDGED
        else f"/api/incidents/{incident.id}/status"
    )

    audit_details: dict[str, Any] = {
        "incident_id": str(incident.id),
        "incident_number": getattr(
            incident,
            "incident_number",
            None,
        ),
        "from_status": previous_status.value,
        "to_status": requested_status.value,
        "reason": reason,
        "resolution_summary": resolution_summary,
        "method": "POST",
        "request_path": request_path,
    }
    audit_details.update(audit_metadata or {})

    repository.create_audit_event(
        db,
        action=audit_action,
        entity_type="Incident",
        entity_id=str(incident.id),
        actor_id=actor_user_id,
        details=audit_details,
    )

    return incident

def update_incident_status(
    db: Session,
    incident_id: UUID,
    request: IncidentStatusUpdateRequest,
    *,
    actor_user_id: str | None = None,
) -> IncidentDetailResponse:
    try:
        incident = _get_required_incident(
            db,
            incident_id,
        )

        _stage_status_update(
            db,
            incident,
            request,
            actor_user_id=actor_user_id,
            occurred_at=_utcnow(),
        )

        db.commit()
        db.refresh(incident)

        return get_incident_detail(
            db,
            incident.id,
        )

    except Exception:
        db.rollback()
        raise

def acknowledge_incident(
    db: Session,
    incident_id: UUID,
    request: IncidentAcknowledgeRequest,
    *,
    actor_user_id: str | None = None,
) -> IncidentDetailResponse:
    """Acknowledge a detected incident in one transaction.

    The operation validates the DETECTED -> ACKNOWLEDGED transition, records
    the acknowledgement timestamp, optionally assigns the incident to the
    actor, writes one timeline event and one audit event, and commits once.
    """
    try:
        incident = _get_required_incident(
            db,
            incident_id,
        )

        now = _utcnow()
        note = _request_text(request, "note")
        assign_to_self = bool(
            getattr(request, "assign_to_self", False)
        )

        assignment_user_id = getattr(
            request,
            "assigned_to_user_id",
            None,
        )

        if assign_to_self:
            if actor_user_id is None:
                raise IncidentConflictError(
                    "assign_to_self requires an authenticated actor"
                )

            assignment_user_id = str(actor_user_id)
        elif assignment_user_id is not None:
            assignment_user_id = str(assignment_user_id)

        status_request = SimpleNamespace(
            status=IncidentStatus.ACKNOWLEDGED,
            reason=note or "Incident acknowledged",
        )

        # Validation happens inside this helper before any status, timeline,
        # or audit mutation is staged. A repeated acknowledgement therefore
        # raises IncidentConflictError instead of silently succeeding.
        _stage_status_update(
            db,
            incident,
            status_request,
            actor_user_id=actor_user_id,
            occurred_at=now,
            timeline_metadata={
                "assign_to_self": assign_to_self,
                "assigned_to_user_id": assignment_user_id,
            },
            audit_metadata={
                "assign_to_self": assign_to_self,
                "assigned_to_user_id": assignment_user_id,
            },
        )

        if assignment_user_id is not None:
            repository.close_current_assignment(
                db,
                incident_id=incident.id,
                unassigned_at=now,
            )

            repository.create_assignment(
                db,
                incident_id=incident.id,
                assigned_to_user_id=assignment_user_id,
                assigned_by_user_id=actor_user_id,
                assignment_note=note,
                assigned_at=now,
            )

            repository.update_incident(
                db,
                incident,
                current_assignee_id=assignment_user_id,
            )

        db.commit()
        db.refresh(incident)

        return get_incident_detail(
            db,
            incident.id,
        )

    except Exception:
        db.rollback()
        raise

def assign_incident(
    db: Session,
    incident_id: UUID,
    request: IncidentAssignRequest | IncidentAssignmentRequest,
    *,
    assigned_by_user_id: str | None = None,
) -> IncidentDetailResponse:
    """Assign an incident while preserving complete assignment history.

    The incident row is locked for the duration of the transaction so two
    concurrent requests cannot both create a new current assignment.
    """
    try:
        incident = _get_required_incident(
            db,
            incident_id,
            for_update=True,
        )

        if IncidentStatus(
            _enum_value(incident.status)
        ) == IncidentStatus.RESOLVED:
            raise IncidentConflictError(
                "A resolved incident cannot be reassigned"
            )

        assigned_to_user_id = str(
            request.assigned_to_user_id
        ).strip()

        # The request schema rejects blank values with HTTP 422. This guard
        # protects non-HTTP callers that construct request-like objects.
        if not assigned_to_user_id:
            raise ValueError(
                "assigned_to_user_id cannot be blank"
            )

        target_user = repository.get_user_by_id(
            db,
            assigned_to_user_id,
        )

        if target_user is None:
            raise IncidentNotFoundError(
                "Assigned user not found"
            )

        current_assignment = (
            repository.get_latest_active_assignment(
                db,
                incident.id,
            )
        )

        if current_assignment is not None:
            current_assignee_id = (
                current_assignment.assigned_to_user_id
            )
        else:
            current_assignee_id = getattr(
                incident,
                "current_assignee_id",
                None,
            )

        normalised_current_assignee_id = (
            str(current_assignee_id)
            if current_assignee_id is not None
            else None
        )

        if (
            normalised_current_assignee_id
            == assigned_to_user_id
        ):
            raise IncidentConflictError(
                "Incident is already assigned to the requested user"
            )

        assignment_note = _request_text(
            request,
            "note",
            "assignment_note",
        )
        assigned_at = _utcnow()

        repository.close_current_assignment(
            db,
            incident_id=incident.id,
            unassigned_at=assigned_at,
        )

        repository.create_assignment(
            db,
            incident_id=incident.id,
            assigned_to_user_id=assigned_to_user_id,
            assigned_by_user_id=assigned_by_user_id,
            assignment_note=assignment_note,
            assigned_at=assigned_at,
        )

        repository.update_incident(
            db,
            incident,
            current_assignee_id=assigned_to_user_id,
        )

        target_display_name = (
            target_user.full_name
            or target_user.email
            or assigned_to_user_id
        )

        repository.create_timeline_event(
            db,
            incident_id=incident.id,
            event_type="OPERATOR_ASSIGNED",
            source="OPERATOR",
            message=(
                assignment_note
                or f"Incident assigned to {target_display_name}."
            ),
            actor_user_id=assigned_by_user_id,
            metadata_json={
                "previous_assignee_user_id": (
                    normalised_current_assignee_id
                ),
                "assigned_to_user_id": assigned_to_user_id,
                "assigned_to_user_email": target_user.email,
            },
            occurred_at=assigned_at,
        )

        repository.create_audit_event(
            db,
            action="INCIDENT_ASSIGNED",
            entity_type="Incident",
            entity_id=str(incident.id),
            actor_id=assigned_by_user_id,
            details={
                "incident_id": str(incident.id),
                "incident_number": getattr(
                    incident,
                    "incident_number",
                    None,
                ),
                "previous_assignee_user_id": (
                    normalised_current_assignee_id
                ),
                "assigned_to_user_id": assigned_to_user_id,
                "assigned_to_user_email": target_user.email,
                "assignment_note": assignment_note,
                "method": "POST",
                "request_path": (
                    f"/api/incidents/{incident.id}/assign"
                ),
            },
        )

        db.commit()
        db.refresh(incident)

        return get_incident_detail(
            db,
            incident.id,
        )

    except Exception:
        db.rollback()
        raise

def add_incident_comment(
    db: Session,
    *,
    incident_id: UUID,
    request: IncidentCommentCreateRequest,
    actor: Any,
) -> IncidentCommentResponse:
    incident = _get_required_incident(
        db,
        incident_id,
    )

    actor_name = get_actor_display_name(actor)
    original_status = incident.status

    try:
        comment = repository.create_comment(
            db,
            incident_id=incident.id,
            author_user_id=str(actor.id),
            comment=request.comment,
        )

        repository.create_timeline_event(
            db,
            incident_id=incident.id,
            event_type=INCIDENT_COMMENT_ADDED,
            source="USER",
            message=(
                f"{actor_name} commented: {request.comment}"
            ),
            actor_user_id=str(actor.id),
            metadata_json={
                "comment_id": str(comment.id),
                "author_user_id": str(actor.id),
            },
            occurred_at=comment.created_at,
        )

        repository.create_audit_event(
            db,
            action="INCIDENT_COMMENT_CREATED",
            entity_type="IncidentComment",
            entity_id=str(comment.id),
            actor_id=str(actor.id),
            details=_json_details(
                incident_id=str(incident.id),
                incident_number=getattr(
                    incident,
                    "incident_number",
                    None,
                ),
                comment_id=str(comment.id),
                comment_length=len(request.comment),
                method="POST",
                request_path=(
                    f"/api/incidents/{incident.id}/comments"
                ),
            ),
        )

        if incident.status != original_status:
            raise RuntimeError(
                "Adding a comment unexpectedly changed incident status"
            )

        db.commit()
        db.refresh(comment)

        return _comment_response(comment)

    except Exception:
        db.rollback()
        raise

def capture_incident_metric(
    db: Session,
    incident_id: UUID,
    *,
    metric_type: str,
    metric_name: str,
    value: float,
    source: str,
    unit: str | None = None,
    captured_at: datetime | None = None,
    metadata_json: dict[str, Any] | None = None,
    actor_user_id: str | None = None,
) -> IncidentMetricResponse:
    try:
        incident = _get_required_incident(
            db,
            incident_id,
        )

        numeric_value = float(value)
        event_time = captured_at or _utcnow()

        metric = repository.create_metric_snapshot(
            db,
            incident_id=incident.id,
            metric_type=metric_type,
            metric_name=metric_name,
            value=numeric_value,
            source=source,
            unit=unit,
            captured_at=event_time,
            metadata_json=metadata_json,
        )

        repository.create_timeline_event(
            db,
            incident_id=incident.id,
            event_type="METRIC_CAPTURED",
            source=source,
            message=(
                f"Captured metric {metric_name}: "
                f"{numeric_value}"
                f"{f' {unit}' if unit else ''}."
            ),
            actor_user_id=actor_user_id,
            metadata_json={
                "metric_id": str(metric.id),
                "metric_type": metric_type,
                "metric_name": metric_name,
                "value": numeric_value,
                "unit": unit,
            },
            occurred_at=event_time,
        )

        repository.create_audit_event(
            db,
            action="INCIDENT_METRIC_CAPTURED",
            entity_type="INCIDENT",
            entity_id=str(incident.id),
            actor_id=actor_user_id,
            details=_json_details(
                metric_id=metric.id,
                metric_type=metric_type,
                metric_name=metric_name,
                value=numeric_value,
                unit=unit,
                source=source,
            ),
        )

        db.commit()
        db.refresh(metric)

        return _metric_response(metric)

    except Exception:
        db.rollback()
        raise

def get_service_runtime_timeline(
    db: Session,
    service_id: str,
    *,
    environment: str | None = None,
    incident_limit: int = 10,
    snapshot_limit: int = 50,
) -> dict[str, Any]:
    """Build the compatibility runtime timeline without router-level SQL."""
    from app.observability.service import (
        get_service_health_history,
    )

    incidents, _total = repository.list_incidents(
        db,
        service_id=service_id,
        environment=environment,
        offset=0,
        limit=incident_limit,
    )

    timeline: list[dict[str, Any]] = []

    for incident in incidents:
        events = repository.get_incident_timeline(
            db,
            incident.id,
        )

        for event in events:
            timeline.append(
                {
                    "source": (event.source or "incident_timeline_events"),
                    "type": event.event_type,
                    "message": event.message,
                    "metadata": {
                        **(event.metadata_json or {}),
                        "incident_id": str(incident.id),
                        "incident_number": (incident.incident_number),
                        "from_status": _enum_value(event.from_status),
                        "to_status": _enum_value(event.to_status),
                        "alert_id": event.alert_id,
                        "deployment_id": (
                            str(event.deployment_id) if event.deployment_id else None
                        ),
                    },
                    "timestamp": event.occurred_at,
                }
            )

    snapshots = get_service_health_history(
        db,
        service_id,
        limit=snapshot_limit,
    )

    for snapshot in snapshots:
        if environment is not None and snapshot.environment != environment:
            continue

        timeline.append(
            {
                "source": "service_health_snapshots",
                "type": "HEALTH_SNAPSHOT",
                "message": (
                    "Service health snapshot recorded "
                    f"with status "
                    f"{_enum_value(snapshot.status)}"
                ),
                "metadata": {
                    "snapshot_id": str(snapshot.id),
                    "service_id": str(snapshot.service_id),
                    "service_name": snapshot.service_name,
                    "environment": snapshot.environment,
                    "status": _enum_value(snapshot.status),
                    "latency_ms": snapshot.latency_ms,
                    "error_rate": snapshot.error_rate,
                    "cpu_usage": snapshot.cpu_usage,
                    "memory_usage": snapshot.memory_usage,
                    "pod_restart_count": (snapshot.pod_restart_count),
                    "replica_count": snapshot.replica_count,
                    "available_replicas": (snapshot.available_replicas),
                    "source": snapshot.source,
                },
                "timestamp": snapshot.created_at,
            }
        )

    timeline.sort(
        key=lambda item: str(item.get("timestamp") or ""),
        reverse=True,
    )

    return {
        "service_id": service_id,
        "timeline": timeline,
    }