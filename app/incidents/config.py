"""Configuration values for the incident response engine."""

from __future__ import annotations

import os


def _positive_int_from_env(name: str, default: int) -> int:
    """Read a positive integer from the environment."""

    raw_value = os.getenv(name, str(default))

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a valid integer, received {raw_value!r}"
        ) from exc

    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")

    return value


def _positive_float_from_env(name: str, default: float) -> float:
    """Read a positive floating-point value from the environment."""

    raw_value = os.getenv(name, str(default))

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a valid number, received {raw_value!r}"
        ) from exc

    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")

    return value


INCIDENT_CORRELATION_WINDOW_MINUTES = _positive_int_from_env(
    "INCIDENT_CORRELATION_WINDOW_MINUTES",
    30,
)

INCIDENT_DEPLOYMENT_CORRELATION_WINDOW_MINUTES = _positive_int_from_env(
    "INCIDENT_DEPLOYMENT_CORRELATION_WINDOW_MINUTES",
    60,
)

INCIDENT_CRITICAL_AVAILABILITY_THRESHOLD = _positive_float_from_env(
    "INCIDENT_CRITICAL_AVAILABILITY_THRESHOLD",
    95.0,
)

INCIDENT_CRITICAL_LATENCY_MULTIPLIER = _positive_float_from_env(
    "INCIDENT_CRITICAL_LATENCY_MULTIPLIER",
    2.0,
)

INCIDENT_HIGH_SEVERITY_ALERT_ESCALATION_COUNT = _positive_int_from_env(
    "INCIDENT_HIGH_SEVERITY_ALERT_ESCALATION_COUNT",
    3,
)

INCIDENT_MULTIPLE_SERVICE_ESCALATION_COUNT = _positive_int_from_env(
    "INCIDENT_MULTIPLE_SERVICE_ESCALATION_COUNT",
    2,
)
