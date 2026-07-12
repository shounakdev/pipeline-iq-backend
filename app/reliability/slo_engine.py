from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Service,
    SLODefinition,
    SLOMeasurement,
    SLOMetricType,
)
from app.reliability.alert_service import (
    create_reliability_alert_and_event,
)
from app.reliability.error_budget import (
    create_error_budget_status,
)
from app.reliability.prometheus_client import (
    get_availability,
    get_error_rate,
    get_p95_latency,
)
from app.models import SLODefinition




MetricGetter = Callable[[str, int], float]


METRIC_GETTERS: dict[
    SLOMetricType,
    MetricGetter,
] = {
    SLOMetricType.AVAILABILITY: get_availability,
    SLOMetricType.P95_LATENCY: get_p95_latency,
    SLOMetricType.ERROR_RATE: get_error_rate,
}


def is_slo_breached(
    metric_type: SLOMetricType,
    measured_value: float,
    target_value: float,
) -> bool:
    if metric_type == SLOMetricType.AVAILABILITY:
        return measured_value < target_value

    if metric_type in {
        SLOMetricType.P95_LATENCY,
        SLOMetricType.ERROR_RATE,
    }:
        return measured_value > target_value

    raise ValueError(
        f"Unsupported SLO metric type: {metric_type}"
    )


def get_enabled_slo_definitions(
    db: Session,
) -> list[SLODefinition]:
    """
    Return all enabled SLO definitions that should be evaluated
    by the scheduled reliability task.
    """

    return (
        db.query(SLODefinition)
        .filter(SLODefinition.enabled.is_(True))
        .all()
    )

def evaluate_slo(
    db: Session,
    slo_definition: SLODefinition,
) -> dict[str, Any]:
    if not slo_definition.enabled:
        raise ValueError(
            "Cannot evaluate a disabled SLO definition"
        )

    service = (
        db.query(Service)
        .filter(
            Service.id
            == slo_definition.service_id
        )
        .first()
    )

    if service is None:
        raise ValueError(
            f"Service not found for SLO "
            f"{slo_definition.id}"
        )

    metric_type = SLOMetricType(
        slo_definition.metric_type
    )

    metric_getter = METRIC_GETTERS.get(
        metric_type
    )

    if metric_getter is None:
        raise ValueError(
            f"No metric getter configured for "
            f"{metric_type.value}"
        )

    measured_value = metric_getter(
        service.name,
        slo_definition.window_minutes,
    )

    breached = is_slo_breached(
        metric_type=metric_type,
        measured_value=measured_value,
        target_value=(
            slo_definition.target_value
        ),
    )

    measurement = SLOMeasurement(
        slo_definition_id=slo_definition.id,
        service_id=slo_definition.service_id,
        metric_type=metric_type,
        measured_value=measured_value,
        target_value=(
            slo_definition.target_value
        ),
        is_breached=breached,
        window_minutes=(
            slo_definition.window_minutes
        ),
        source="PROMETHEUS",
    )

    error_budget = None
    reliability_alert = None
    outbox_event = None
    alert_created = False

    try:
        # Flush first so measurement.id is available to
        # the budget status and event payload.
        db.add(measurement)
        db.flush()

        error_budget = (
            create_error_budget_status(
                db,
                slo_definition=slo_definition,
                measurement=measurement,
            )
        )

        (
            reliability_alert,
            outbox_event,
            alert_created,
        ) = create_reliability_alert_and_event(
            db,
            service=service,
            slo_definition=slo_definition,
            measurement=measurement,
            error_budget=error_budget,
        )

        # Measurement, error budget, alert and outbox
        # event succeed or fail together.
        db.commit()

        db.refresh(measurement)

        if error_budget is not None:
            db.refresh(error_budget)

        if reliability_alert is not None:
            db.refresh(reliability_alert)

        if outbox_event is not None:
            db.refresh(outbox_event)

    except Exception:
        db.rollback()
        raise

    return {
        "measurement_id": measurement.id,
        "slo_definition_id": (
            slo_definition.id
        ),
        "service_id": service.id,
        "service_name": service.name,
        "metric_type": metric_type,
        "target_value": (
            slo_definition.target_value
        ),
        "measured_value": measured_value,
        "is_breached": breached,
        "window_minutes": (
            slo_definition.window_minutes
        ),
        "source": measurement.source,
        "evaluated_at": (
            measurement.evaluated_at
        ),

        # Sprint 6E
        "error_budget_status_id": (
            error_budget.id
            if error_budget is not None
            else None
        ),
        "error_budget_remaining": (
            error_budget.remaining_percentage
            if error_budget is not None
            else None
        ),
        "error_budget_consumed": (
            error_budget.consumed_percentage
            if error_budget is not None
            else None
        ),
        "burn_rate": (
            error_budget.burn_rate
            if error_budget is not None
            else None
        ),
        "error_budget_state": (
            error_budget.status
            if error_budget is not None
            else None
        ),

        # Sprint 6F
        "reliability_alert_id": (
            reliability_alert.id
            if reliability_alert is not None
            else None
        ),
        "reliability_alert_type": (
            reliability_alert.alert_type
            if reliability_alert is not None
            else None
        ),
        "alert_created": alert_created,
        "alert_event_id": (
            outbox_event.event_id
            if outbox_event is not None
            else None
        ),
    }
