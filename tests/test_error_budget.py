import pytest

from app.models import ErrorBudgetState
from app.reliability.error_budget import (
    calculate_availability_error_budget,
)


def test_availability_error_budget_is_exhausted():
    """
    Target availability: 99.9%
    Measured availability: 99.5%

    Allowed failure: 0.1%
    Actual failure: 0.5%
    Consumed: 500%
    Remaining: 0%
    """
    result = calculate_availability_error_budget(
        target_percentage=99.9,
        measured_availability=99.5,
    )

    assert result.allowed_failure_percentage == pytest.approx(
        0.1
    )
    assert result.actual_failure_percentage == pytest.approx(
        0.5
    )
    assert result.consumed_percentage == pytest.approx(
        500.0
    )
    assert result.remaining_percentage == pytest.approx(
        0.0
    )
    assert result.burn_rate == pytest.approx(5.0)
    assert result.status == ErrorBudgetState.EXHAUSTED
    assert result.rapid_burn is True


@pytest.mark.parametrize(
    (
        "measured_availability",
        "expected_remaining",
        "expected_status",
    ),
    [
        (
            100.0,
            100.0,
            ErrorBudgetState.HEALTHY,
        ),
        (
            99.95,
            50.0,
            ErrorBudgetState.HEALTHY,
        ),
        (
            99.92,
            20.0,
            ErrorBudgetState.WARNING,
        ),
        (
            99.91,
            10.0,
            ErrorBudgetState.BREACHED,
        ),
        (
            99.90,
            0.0,
            ErrorBudgetState.EXHAUSTED,
        ),
    ],
)
def test_error_budget_boundaries(
    measured_availability,
    expected_remaining,
    expected_status,
):
    result = calculate_availability_error_budget(
        target_percentage=99.9,
        measured_availability=measured_availability,
    )

    assert result.remaining_percentage == pytest.approx(
        expected_remaining
    )
    assert result.status == expected_status
