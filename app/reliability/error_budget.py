from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    ErrorBudgetState,
    ErrorBudgetStatus,
    SLODefinition,
    SLOMeasurement,
    SLOMetricType,
)


RAPID_BURN_THRESHOLD = 2.0


@dataclass(frozen=True)
class ErrorBudgetCalculation:
    target_percentage: float
    allowed_failure_percentage: float
    actual_failure_percentage: float
    consumed_percentage: float
    remaining_percentage: float
    burn_rate: float
    status: ErrorBudgetState
    rapid_burn: bool


def classify_error_budget(
    remaining_percentage: float,
) -> ErrorBudgetState:
    """
    Exact boundary rules:

    remaining >= 50       -> HEALTHY
    20 <= remaining < 50  -> WARNING
    0 < remaining < 20    -> BREACHED
    remaining <= 0        -> EXHAUSTED
    """
    if remaining_percentage <= 0:
        return ErrorBudgetState.EXHAUSTED

    if remaining_percentage < 20:
        return ErrorBudgetState.BREACHED

    if remaining_percentage < 50:
        return ErrorBudgetState.WARNING

    return ErrorBudgetState.HEALTHY


def calculate_availability_error_budget(
    target_percentage: float,
    measured_availability: float,
) -> ErrorBudgetCalculation:
    target_percentage = float(target_percentage)
    measured_availability = float(measured_availability)

    if not 0 < target_percentage < 100:
        raise ValueError(
            "Availability target must be greater than 0 "
            "and less than 100"
        )

    if not 0 <= measured_availability <= 100:
        raise ValueError(
            "Measured availability must be between 0 and 100"
        )

    allowed_failure_percentage = (
        100.0 - target_percentage
    )

    actual_failure_percentage = max(
        0.0,
        100.0 - measured_availability,
    )

    consumed_percentage = (
        actual_failure_percentage
        / allowed_failure_percentage
        * 100.0
    )

    raw_remaining_percentage = (
        100.0 - consumed_percentage
    )

    # The stored/displayed value should not become negative.
    remaining_percentage = round(
        max(
            0.0,
            100.0 - consumed_percentage,
        ),
        10,
    )

    burn_rate = consumed_percentage / 100.0

    status = classify_error_budget(
        remaining_percentage
    )

    return ErrorBudgetCalculation(
        target_percentage=target_percentage,
        allowed_failure_percentage=(
            allowed_failure_percentage
        ),
        actual_failure_percentage=(
            actual_failure_percentage
        ),
        consumed_percentage=consumed_percentage,
        remaining_percentage=remaining_percentage,
        burn_rate=burn_rate,
        status=status,
        rapid_burn=(
            burn_rate >= RAPID_BURN_THRESHOLD
        ),
    )


def create_error_budget_status(
    db: Session,
    *,
    slo_definition: SLODefinition,
    measurement: SLOMeasurement,
) -> ErrorBudgetStatus | None:
    """
    Create one error-budget snapshot for an availability
    measurement.

    No commit is performed here. The SLO engine owns the
    transaction.
    """
    metric_type = SLOMetricType(
        slo_definition.metric_type
    )

    if metric_type != SLOMetricType.AVAILABILITY:
        return None

    calculation = (
        calculate_availability_error_budget(
            target_percentage=(
                slo_definition.target_value
            ),
            measured_availability=(
                measurement.measured_value
            ),
        )
    )

    status = ErrorBudgetStatus(
        slo_definition_id=slo_definition.id,
        service_id=slo_definition.service_id,
        target_percentage=(
            calculation.target_percentage
        ),
        allowed_failure_percentage=(
            calculation.allowed_failure_percentage
        ),
        consumed_percentage=(
            calculation.consumed_percentage
        ),
        remaining_percentage=(
            calculation.remaining_percentage
        ),
        burn_rate=calculation.burn_rate,
        status=calculation.status,
        window_minutes=(
            slo_definition.window_minutes
        ),
    )

    db.add(status)
    db.flush()

    return status
