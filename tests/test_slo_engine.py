from app.models import SLOMetricType
from app.reliability.slo_engine import is_slo_breached


def test_availability_slo_calculation_is_breached():
    """
    Availability is breached when the measured value is
    below the configured target.
    """
    result = is_slo_breached(
        metric_type=SLOMetricType.AVAILABILITY,
        measured_value=99.5,
        target_value=99.9,
    )

    assert result is True


def test_latency_slo_calculation_is_breached():
    """
    Latency is breached when the measured value is
    above the configured maximum.
    """
    result = is_slo_breached(
        metric_type=SLOMetricType.P95_LATENCY,
        measured_value=2300.0,
        target_value=500.0,
    )

    assert result is True


def test_healthy_availability_is_not_breached():
    result = is_slo_breached(
        metric_type=SLOMetricType.AVAILABILITY,
        measured_value=99.95,
        target_value=99.9,
    )

    assert result is False


def test_healthy_latency_is_not_breached():
    result = is_slo_breached(
        metric_type=SLOMetricType.P95_LATENCY,
        measured_value=420.0,
        target_value=500.0,
    )

    assert result is False


def test_error_rate_above_target_is_breached():
    result = is_slo_breached(
        metric_type=SLOMetricType.ERROR_RATE,
        measured_value=2.5,
        target_value=1.0,
    )

    assert result is True
