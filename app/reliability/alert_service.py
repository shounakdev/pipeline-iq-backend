from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from app.events.constants import RELIABILITY_ALERT_CREATED
from app.events.service import record_platform_event
from app.models import (
    Deployment,
    Environment,
    ErrorBudgetState,
    ErrorBudgetStatus,
    ReliabilityAlert,
    ReliabilityAlertStatus,
    ReliabilityAlertType,
    ReliabilitySeverity,
    Service,
    SLODefinition,
    SLOMeasurement,
    SLOMetricType,
)


RAPID_BURN_THRESHOLD = 2.0

ACTIVE_ALERT_STATUSES = (
    ReliabilityAlertStatus.OPEN,
    ReliabilityAlertStatus.ACKNOWLEDGED,
)


def _find_latest_deployment(
    db: Session,
    *,
    service_id: str,
    occurred_at: datetime | None = None,
    environment_id: str | None = None,
) -> Deployment | None:
    correlation_time = occurred_at or datetime.now(
        timezone.utc
    )

    query = db.query(Deployment).filter(
        Deployment.service_id == service_id,
        Deployment.created_at <= correlation_time,
    )

    if environment_id is not None:
        query = query.filter(
            Deployment.environment_id == environment_id
        )

    return (
        query.order_by(
            Deployment.created_at.desc()
        )
        .first()
    )


def get_deployment_environment(
    db: Session,
    *,
    deployment: Deployment | None,
) -> str:
    if (
        deployment is not None
        and deployment.environment_id
    ):
        environment = (
            db.query(Environment)
            .filter(
                Environment.id
                == deployment.environment_id
            )
            .first()
        )

        if environment is not None:
            return environment.name

    return "staging"


def get_metric_alert_type(
    metric_type: SLOMetricType,
) -> ReliabilityAlertType:
    mapping = {
        SLOMetricType.AVAILABILITY: (
            ReliabilityAlertType.AVAILABILITY_BREACH
        ),
        SLOMetricType.P95_LATENCY: (
            ReliabilityAlertType.LATENCY_BREACH
        ),
        SLOMetricType.ERROR_RATE: (
            ReliabilityAlertType.ERROR_RATE_BREACH
        ),
    }

    return mapping.get(
        metric_type,
        ReliabilityAlertType.SLO_BREACH,
    )


def determine_alert_type(
    *,
    measurement: SLOMeasurement,
    error_budget: ErrorBudgetStatus | None,
) -> ReliabilityAlertType | None:
    """
    Return the highest-priority alert for this evaluation.

    Priority:
    1. Exhausted error budget
    2. Breached or rapidly burning error budget
    3. Direct SLO breach
    """
    if error_budget is not None:
        state = ErrorBudgetState(
            error_budget.status
        )

        if state == ErrorBudgetState.EXHAUSTED:
            return (
                ReliabilityAlertType
                .ERROR_BUDGET_EXHAUSTED
            )

        if (
            state == ErrorBudgetState.BREACHED
            or error_budget.burn_rate
            >= RAPID_BURN_THRESHOLD
        ):
            return (
                ReliabilityAlertType
                .ERROR_BUDGET_BURN
            )

    if measurement.is_breached:
        return get_metric_alert_type(
            SLOMetricType(measurement.metric_type)
        )

    return None


def resolve_active_reliability_alerts(
    db: Session,
    *,
    service_id: str,
    slo_definition_id: str,
    alert_type: ReliabilityAlertType,
) -> int:
    """
    Resolve active alerts for one exact service, SLO
    definition and alert type.

    Alerts belonging to another SLO or another alert
    type are not modified.
    """
    active_alerts = (
        db.query(ReliabilityAlert)
        .filter(
            ReliabilityAlert.service_id
            == service_id,
            ReliabilityAlert.slo_definition_id
            == slo_definition_id,
            ReliabilityAlert.alert_type
            == alert_type,
            ReliabilityAlert.status.in_(
                ACTIVE_ALERT_STATUSES
            ),
        )
        .all()
    )

    if not active_alerts:
        return 0

    resolved_at = datetime.now(timezone.utc)

    for alert in active_alerts:
        alert.status = (
            ReliabilityAlertStatus.RESOLVED
        )
        alert.resolved_at = resolved_at

    db.flush()

    return len(active_alerts)


def _resolve_inactive_alert_types(
    db: Session,
    *,
    service_id: str,
    slo_definition_id: str,
    measurement: SLOMeasurement,
    active_alert_type: (
        ReliabilityAlertType | None
    ),
) -> int:
    """
    Resolve alert types managed by this SLO that are no
    longer active.

    This also handles transitions such as:

    ERROR_BUDGET_EXHAUSTED -> healthy
    ERROR_BUDGET_EXHAUSTED -> ERROR_BUDGET_BURN
    ERROR_BUDGET_BURN -> direct metric breach
    direct metric breach -> healthy
    """
    metric_alert_type = get_metric_alert_type(
        SLOMetricType(measurement.metric_type)
    )

    managed_alert_types = {
        ReliabilityAlertType.ERROR_BUDGET_EXHAUSTED,
        ReliabilityAlertType.ERROR_BUDGET_BURN,
        metric_alert_type,
    }

    resolved_count = 0

    for alert_type in managed_alert_types:
        if alert_type == active_alert_type:
            continue

        resolved_count += (
            resolve_active_reliability_alerts(
                db,
                service_id=service_id,
                slo_definition_id=(
                    slo_definition_id
                ),
                alert_type=alert_type,
            )
        )

    return resolved_count


def find_existing_open_alert(
    db: Session,
    *,
    service_id: str,
    slo_definition_id: str,
    alert_type: ReliabilityAlertType,
) -> ReliabilityAlert | None:
    """
    Find an existing OPEN or ACKNOWLEDGED alert for the
    same service, SLO definition and alert type.

    This prevents a new row from being created every time
    the periodic evaluator runs.
    """
    return (
        db.query(ReliabilityAlert)
        .filter(
            ReliabilityAlert.service_id
            == service_id,
            ReliabilityAlert.slo_definition_id
            == slo_definition_id,
            ReliabilityAlert.alert_type
            == alert_type,
            ReliabilityAlert.status.in_(
                ACTIVE_ALERT_STATUSES
            ),
        )
        .order_by(
            ReliabilityAlert.created_at.desc()
        )
        .first()
    )


def create_reliability_alert_and_event(
    db: Session,
    *,
    service: Service,
    slo_definition: SLODefinition,
    measurement: SLOMeasurement,
    error_budget: ErrorBudgetStatus | None,
) -> tuple[
    ReliabilityAlert | None,
    Any | None,
    bool,
]:
    service_id = str(service.id)
    slo_definition_id = str(
        slo_definition.id
    )

    alert_type = determine_alert_type(
        measurement=measurement,
        error_budget=error_budget,
    )

    # Resolve alerts that no longer match the current
    # condition. When alert_type is None, all alert types
    # managed by this SLO are resolved.
    _resolve_inactive_alert_types(
        db,
        service_id=service_id,
        slo_definition_id=slo_definition_id,
        measurement=measurement,
        active_alert_type=alert_type,
    )

    # The SLO and its error budget are currently healthy.
    # Any previously active alert was resolved above.
    if alert_type is None:
        return None, None, False

    severity = ReliabilitySeverity(
        slo_definition.severity_on_breach
    )

    triggered_value = float(
        measurement.measured_value
    )
    threshold_value = float(
        measurement.target_value
    )

    existing_alert = find_existing_open_alert(
        db,
        service_id=service_id,
        slo_definition_id=slo_definition_id,
        alert_type=alert_type,
    )

    if existing_alert is not None:
        # Refresh the existing alert with the latest
        # evaluated values instead of creating a duplicate.
        existing_alert.triggered_value = (
            triggered_value
        )
        existing_alert.threshold_value = (
            threshold_value
        )
        existing_alert.severity = severity

        db.flush()

        return existing_alert, None, False

    alert_created_at = datetime.now(timezone.utc)

    latest_deployment = _find_latest_deployment(
        db,
        service_id=slo_definition.service_id,
        occurred_at=alert_created_at,
        environment_id=getattr(
            slo_definition,
            "environment_id",
            None,
        ),
    )

    environment = get_deployment_environment(
        db,
        deployment=latest_deployment,
    )

    alert = ReliabilityAlert(
        service_id=service_id,
        slo_definition_id=slo_definition_id,
        alert_type=alert_type,
        severity=severity,
        triggered_value=triggered_value,
        threshold_value=threshold_value,
        deployment_id=(
            latest_deployment.id
            if latest_deployment is not None
            else None
        ),
        status=ReliabilityAlertStatus.OPEN,
        created_at=alert_created_at,
    )

    db.add(alert)
    db.flush()

    metric_type = SLOMetricType(
        measurement.metric_type
    )

    correlation_id = (
        f"{service.id}:"
        f"{environment}:"
        f"{metric_type.value}"
    )

    payload = {
        "alert_id": str(alert.id),
        "alert_type": alert_type.value,
        "created_at": alert_created_at.isoformat(),

        # Keep these in the payload because the
        # transactional outbox envelope may not place
        # them at the top level.
        "severity": severity.value,
        "service_name": service.name,
        "source": "platformiq-reliability",
        "reliability_alert_id": str(alert.id),
        "slo_definition_id": slo_definition_id,
        "measurement_id": str(measurement.id),
        "metric_type": metric_type.value,
        "triggered_value": triggered_value,
        "threshold_value": threshold_value,
        "is_breached": bool(
            measurement.is_breached
        ),
        "window_minutes": int(
            measurement.window_minutes
        ),
        "deployment_id": (
            str(latest_deployment.id)
            if latest_deployment is not None
            else None
        ),
        "error_budget_remaining": (
            float(
                error_budget.remaining_percentage
            )
            if error_budget is not None
            else None
        ),
        "error_budget_consumed": (
            float(
                error_budget.consumed_percentage
            )
            if error_budget is not None
            else None
        ),
        "burn_rate": (
            float(error_budget.burn_rate)
            if error_budget is not None
            else None
        ),
        "error_budget_status": (
            ErrorBudgetState(
                error_budget.status
            ).value
            if error_budget is not None
            else None
        ),
        "rapid_burn": (
            bool(
                error_budget.burn_rate
                >= RAPID_BURN_THRESHOLD
            )
            if error_budget is not None
            else False
        ),
    }

    outbox_event = record_platform_event(
        db,
        event_type=RELIABILITY_ALERT_CREATED,
        correlation_id=correlation_id,
        service_id=service_id,
        environment=environment,
        payload=payload,
    )

    return alert, outbox_event, True