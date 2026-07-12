from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Deployment,
    ErrorBudgetStatus,
    ReliabilityAlert,
    ReliabilityAlertStatus,
    Service,
    SLODefinition,
    SLOMeasurement,
)
from app.reliability.schemas import (
    ErrorBudgetItemResponse,
    ReliabilityAlertDetailResponse,
    ReliabilityAlertResponse,
    ReliabilityDeploymentResponse,
    ReliabilitySLODefinitionSummary,
    ReliabilitySLOStateResponse,
    ServiceErrorBudgetResponse,
    ServiceReliabilityResponse,
)


ACTIVE_ALERT_STATUSES = (
    ReliabilityAlertStatus.OPEN,
    ReliabilityAlertStatus.ACKNOWLEDGED,
)


def _get_service(
    db: Session,
    service_id: str,
) -> Service:
    """
    Load a service or raise LookupError.

    The reliability router can translate LookupError into HTTP 404.
    """
    service = (
        db.query(Service)
        .filter(Service.id == service_id)
        .first()
    )

    if service is None:
        raise LookupError(
            f"Service with id '{service_id}' was not found."
        )

    return service


def _get_latest_measurement(
    db: Session,
    slo_definition_id: str,
) -> SLOMeasurement | None:
    """
    Return the newest measurement for one SLO definition.
    """
    return (
        db.query(SLOMeasurement)
        .filter(
            SLOMeasurement.slo_definition_id
            == slo_definition_id
        )
        .order_by(
            SLOMeasurement.evaluated_at.desc(),
            SLOMeasurement.created_at.desc(),
        )
        .first()
    )


def _get_latest_error_budget(
    db: Session,
    slo_definition_id: str,
) -> ErrorBudgetStatus | None:
    """
    Return the newest error-budget status for one SLO definition.
    """
    return (
        db.query(ErrorBudgetStatus)
        .filter(
            ErrorBudgetStatus.slo_definition_id
            == slo_definition_id
        )
        .order_by(
            ErrorBudgetStatus.evaluated_at.desc(),
            ErrorBudgetStatus.created_at.desc(),
        )
        .first()
    )


def _string_value(value: Any) -> str | None:
    """
    Convert strings, UUIDs and Enum values into response strings.
    """
    if value is None:
        return None

    enum_value = getattr(value, "value", None)

    if enum_value is not None:
        return str(enum_value)

    return str(value)


def _enum_value(value: object | None) -> str:
    """
    Normalize strings and Enum values for status comparisons.
    """
    if value is None:
        return ""

    raw_value = getattr(value, "value", value)

    return str(raw_value).upper()


def calculate_overall_reliability_status(
    slos: list[Any],
    error_budget: object | None = None,
) -> str:
    """
    Calculate service-level reliability from evaluated SLOs only.

    Unevaluated SLOs do not force the whole service to NO_DATA.
    Error-budget state is read from evaluated SLO response items and,
    when supplied, from one error-budget object or a collection of them.
    """
    evaluated_slos = [
        slo
        for slo in slos
        if getattr(slo, "measured_value", None) is not None
        and getattr(slo, "evaluated_at", None) is not None
    ]

    slo_states = {
        _enum_value(getattr(slo, "status", None))
        for slo in evaluated_slos
    }

    error_budget_states = {
        _enum_value(
            getattr(
                slo,
                "error_budget_state",
                None,
            )
        )
        for slo in evaluated_slos
    }

    if error_budget is not None:
        error_budgets = (
            error_budget
            if isinstance(
                error_budget,
                (list, tuple, set),
            )
            else (error_budget,)
        )

        for budget in error_budgets:
            budget_state = getattr(
                budget,
                "state",
                None,
            )

            if budget_state is None:
                budget_state = getattr(
                    budget,
                    "status",
                    None,
                )

            error_budget_states.add(
                _enum_value(budget_state)
            )

    error_budget_states.discard("")

    if (
        "BREACHED" in slo_states
        or error_budget_states.intersection(
            {"BREACHED", "EXHAUSTED"}
        )
    ):
        return "BREACHED"

    if (
        "WARNING" in slo_states
        or "WARNING" in error_budget_states
    ):
        return "WARNING"

    if evaluated_slos:
        return "HEALTHY"

    return "NO_DATA"


def _get_deployment_environment(
    deployment: Deployment,
) -> str | None:
    """
    Prefer an Environment relationship name when available.

    Fall back to environment_id because the current Deployment model
    stores environment_id rather than a direct environment string.
    """
    environment = getattr(
        deployment,
        "environment",
        None,
    )

    if environment is not None:
        if isinstance(environment, str):
            return environment

        environment_name = getattr(
            environment,
            "name",
            None,
        )

        if environment_name is not None:
            return _string_value(environment_name)

    return _string_value(
        getattr(
            deployment,
            "environment_id",
            None,
        )
    )


def _get_deployment_status(
    deployment: Deployment,
) -> str | None:
    """
    Resolve a readable deployment status.

    The current Deployment model may use rollout-specific fields rather
    than a generic status field.
    """
    status = getattr(
        deployment,
        "status",
        None,
    )

    if status is None:
        status = getattr(
            deployment,
            "kubernetes_rollout_status",
            None,
        )

    if status is None:
        status = getattr(
            deployment,
            "argo_sync_status",
            None,
        )

    return _string_value(status)


def _deployment_response(
    deployment: Deployment | None,
) -> ReliabilityDeploymentResponse | None:
    if deployment is None:
        return None

    return ReliabilityDeploymentResponse(
        id=str(deployment.id),
        environment=_get_deployment_environment(
            deployment
        ),
        status=_get_deployment_status(deployment),
        created_at=deployment.created_at,
    )


def _alert_payload(
    alert: ReliabilityAlert,
) -> dict[str, Any]:
    """
    Build the common response fields shared by alert list and detail.
    """
    return {
        "id": str(alert.id),
        "service_id": str(alert.service_id),
        "slo_definition_id": (
            str(alert.slo_definition_id)
            if alert.slo_definition_id is not None
            else None
        ),
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "triggered_value": float(
            alert.triggered_value
        ),
        "threshold_value": float(
            alert.threshold_value
        ),
        "deployment_id": (
            str(alert.deployment_id)
            if alert.deployment_id is not None
            else None
        ),
        "status": alert.status,
        "created_at": alert.created_at,
        "resolved_at": alert.resolved_at,
    }


def _alert_response(
    alert: ReliabilityAlert,
) -> ReliabilityAlertResponse:
    return ReliabilityAlertResponse(
        **_alert_payload(alert)
    )


def get_service_reliability(
    db: Session,
    service_id: str,
) -> ServiceReliabilityResponse:
    """
    Return the reliability overview for a service.

    Rules:
    - Include enabled SLO definitions only.
    - Use the newest measurement for each SLO.
    - Use the newest error-budget status for each SLO.
    - No measurement means that individual SLO is NO_DATA.
    - Breached measurement means that individual SLO is BREACHED.
    - Otherwise the evaluated SLO is HEALTHY.
    - Overall status ignores unevaluated optional SLOs.
    - OPEN and ACKNOWLEDGED alerts are both active.
    - Include the newest deployment for the service.
    """
    service_id = str(service_id)
    service = _get_service(db, service_id)

    slo_definitions = (
        db.query(SLODefinition)
        .filter(
            SLODefinition.service_id == service_id,
            SLODefinition.enabled.is_(True),
        )
        .order_by(
            SLODefinition.created_at.asc()
        )
        .all()
    )

    slo_states: list[
        ReliabilitySLOStateResponse
    ] = []
    evaluated_error_budgets: list[
        ErrorBudgetStatus
    ] = []

    for slo_definition in slo_definitions:
        slo_definition_id = str(
            slo_definition.id
        )

        measurement = _get_latest_measurement(
            db,
            slo_definition_id,
        )

        error_budget = _get_latest_error_budget(
            db,
            slo_definition_id,
        )

        if measurement is None:
            reliability_status = "NO_DATA"
            measured_value = None
            evaluated_at = None
        else:
            reliability_status = (
                "BREACHED"
                if measurement.is_breached
                else "HEALTHY"
            )
            measured_value = float(
                measurement.measured_value
            )
            evaluated_at = (
                measurement.evaluated_at
            )

            if error_budget is not None:
                evaluated_error_budgets.append(
                    error_budget
                )

        slo_states.append(
            ReliabilitySLOStateResponse(
                slo_definition_id=(
                    slo_definition_id
                ),
                metric_type=(
                    slo_definition.metric_type
                ),
                target_value=float(
                    slo_definition.target_value
                ),
                measured_value=measured_value,
                status=reliability_status,
                evaluated_at=evaluated_at,
                error_budget_state=(
                    error_budget.status
                    if error_budget is not None
                    else None
                ),
            )
        )

    overall_status = (
        calculate_overall_reliability_status(
            slos=slo_states,
            error_budget=evaluated_error_budgets,
        )
    )

    active_alerts = (
        db.query(ReliabilityAlert)
        .filter(
            ReliabilityAlert.service_id
            == service_id,
            ReliabilityAlert.status.in_(
                ACTIVE_ALERT_STATUSES
            ),
        )
        .order_by(
            ReliabilityAlert.created_at.desc()
        )
        .all()
    )

    latest_deployment = (
        db.query(Deployment)
        .filter(
            Deployment.service_id == service_id
        )
        .order_by(
            Deployment.created_at.desc()
        )
        .first()
    )

    return ServiceReliabilityResponse(
        service_id=str(service.id),
        service_name=service.name,
        overall_status=overall_status,
        slos=slo_states,
        open_alerts=[
            _alert_response(alert)
            for alert in active_alerts
        ],
        latest_deployment=(
            _deployment_response(
                latest_deployment
            )
        ),
    )


def get_service_error_budget(
    db: Session,
    service_id: str,
) -> ServiceErrorBudgetResponse:
    """
    Return only the newest ErrorBudgetStatus for each SLO definition.

    SLOs without an error-budget evaluation are omitted because the
    ErrorBudgetItemResponse fields require an evaluated result.
    """
    service_id = str(service_id)

    # Validate that the requested service exists.
    _get_service(db, service_id)

    slo_definitions = (
        db.query(SLODefinition)
        .filter(
            SLODefinition.service_id
            == service_id
        )
        .order_by(
            SLODefinition.created_at.asc()
        )
        .all()
    )

    budgets: list[ErrorBudgetItemResponse] = []

    for slo_definition in slo_definitions:
        slo_definition_id = str(
            slo_definition.id
        )

        error_budget = _get_latest_error_budget(
            db,
            slo_definition_id,
        )

        if error_budget is None:
            continue

        budgets.append(
            ErrorBudgetItemResponse(
                slo_definition_id=(
                    slo_definition_id
                ),
                metric_type=(
                    slo_definition.metric_type
                ),
                target_percentage=float(
                    error_budget.target_percentage
                ),
                remaining_percentage=float(
                    error_budget.remaining_percentage
                ),
                consumed_percentage=float(
                    error_budget.consumed_percentage
                ),
                burn_rate=float(
                    error_budget.burn_rate
                ),
                status=error_budget.status,
                evaluated_at=(
                    error_budget.evaluated_at
                ),
            )
        )

    return ServiceErrorBudgetResponse(
        service_id=service_id,
        budgets=budgets,
    )


def list_reliability_alerts(
    db: Session,
) -> list[ReliabilityAlertResponse]:
    """
    Return the complete reliability-alert history, newest first.

    OPEN and ACKNOWLEDGED filtering is applied to the service
    reliability overview's open_alerts field, not to this history list.
    """
    alerts = (
        db.query(ReliabilityAlert)
        .order_by(
            ReliabilityAlert.created_at.desc()
        )
        .all()
    )

    return [
        _alert_response(alert)
        for alert in alerts
    ]


def get_reliability_alert(
    db: Session,
    alert_id: str,
) -> ReliabilityAlertDetailResponse | None:
    """
    Return alert details with its SLO definition and correlated
    deployment when available.
    """
    alert = (
        db.query(ReliabilityAlert)
        .filter(
            ReliabilityAlert.id == alert_id
        )
        .first()
    )

    if alert is None:
        return None

    slo_definition = None

    if alert.slo_definition_id is not None:
        slo_definition = (
            db.query(SLODefinition)
            .filter(
                SLODefinition.id
                == alert.slo_definition_id
            )
            .first()
        )

    deployment = None

    if alert.deployment_id is not None:
        deployment = (
            db.query(Deployment)
            .filter(
                Deployment.id
                == alert.deployment_id
            )
            .first()
        )

    slo_definition_response = None

    if slo_definition is not None:
        slo_definition_response = (
            ReliabilitySLODefinitionSummary(
                id=str(slo_definition.id),
                service_id=str(
                    slo_definition.service_id
                ),
                metric_type=(
                    slo_definition.metric_type
                ),
                target_value=float(
                    slo_definition.target_value
                ),
                window_minutes=(
                    slo_definition.window_minutes
                ),
                enabled=slo_definition.enabled,
            )
        )

    return ReliabilityAlertDetailResponse(
        **_alert_payload(alert),
        slo_definition=(
            slo_definition_response
        ),
        deployment=_deployment_response(
            deployment
        ),
    )