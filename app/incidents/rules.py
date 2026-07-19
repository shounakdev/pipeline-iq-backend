"""Pure incident deduplication and severity calculation rules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.incidents.config import (
    INCIDENT_CRITICAL_AVAILABILITY_THRESHOLD,
    INCIDENT_CRITICAL_LATENCY_MULTIPLIER,
    INCIDENT_HIGH_SEVERITY_ALERT_ESCALATION_COUNT,
    INCIDENT_MULTIPLE_SERVICE_ESCALATION_COUNT,
)
from app.models import IncidentSeverity, ReliabilitySeverity


RELIABILITY_TO_INCIDENT_SEVERITY = {
    ReliabilitySeverity.CRITICAL: IncidentSeverity.SEV_1,
    ReliabilitySeverity.HIGH: IncidentSeverity.SEV_2,
    ReliabilitySeverity.MEDIUM: IncidentSeverity.SEV_3,
    ReliabilitySeverity.LOW: IncidentSeverity.SEV_3,
}

SEVERITY_RANK = {
    IncidentSeverity.SEV_3: 1,
    IncidentSeverity.SEV_2: 2,
    IncidentSeverity.SEV_1: 3,
}

NON_PRODUCTION_ENVIRONMENTS = {
    "development",
    "dev",
    "test",
    "testing",
    "qa",
    "staging",
    "sandbox",
}


@dataclass(frozen=True)
class SeverityDecision:
    """Explainable result produced by the incident severity engine."""

    severity: IncidentSeverity
    reason_code: str
    explanation: str
    evidence: dict[str, Any]


def _enum_value(value: Any) -> str:
    """Return the stored value of an enum or its string value."""

    if isinstance(value, Enum):
        return str(value.value)

    return str(value)


def _normalise_key_part(value: Any, field_name: str) -> str:
    """Normalise one deduplication-key component."""

    if value is None:
        raise ValueError(f"{field_name} is required")

    normalised = _enum_value(value).strip().lower()

    if not normalised:
        raise ValueError(f"{field_name} must not be empty")

    return normalised.replace(":", "-")


def build_deduplication_key(
    service_id: Any,
    environment: str,
    slo_or_alert_category: Any,
) -> str:
    """Build a stable service, environment, and SLO/category key."""

    return ":".join(
        (
            _normalise_key_part(service_id, "service_id"),
            _normalise_key_part(environment, "environment"),
            _normalise_key_part(
                slo_or_alert_category,
                "slo_or_alert_category",
            ),
        )
    )


def build_deduplication_lock_id(
    deduplication_key: str,
) -> int:
    """
    Build a stable signed 64-bit PostgreSQL advisory-lock ID.

    Python's built-in hash() is intentionally not used because its
    result changes between interpreter processes.
    """

    normalised_key = deduplication_key.strip()

    if not normalised_key:
        raise ValueError("deduplication_key must not be empty")

    digest = hashlib.blake2b(
        normalised_key.encode("utf-8"),
        digest_size=8,
        person=b"incident-lock",
    ).digest()

    return int.from_bytes(
        digest,
        byteorder="big",
        signed=True,
    )


def _normalise_reliability_severity(
    severity: ReliabilitySeverity | str,
) -> ReliabilitySeverity:
    """Convert a reliability-severity string or enum to its enum."""

    if isinstance(severity, ReliabilitySeverity):
        return severity

    try:
        return ReliabilitySeverity(str(severity).strip().upper())
    except ValueError as exc:
        raise ValueError(
            f"Unsupported reliability severity: {severity!r}"
        ) from exc


def is_more_severe(
    candidate: IncidentSeverity,
    current: IncidentSeverity,
) -> bool:
    """Return whether the candidate severity outranks the current value."""

    return SEVERITY_RANK[candidate] > SEVERITY_RANK[current]


def calculate_incident_severity_decision(
    reliability_severity: ReliabilitySeverity | str,
    *,
    environment: str = "production",
    alert_type: Any | None = None,
    service_criticality: str | None = None,
    measured_value: float | None = None,
    threshold_value: float | None = None,
    availability_percent: float | None = None,
    affected_service_count: int = 1,
    high_severity_alert_count: int = 0,
    deployment_correlated: bool = False,
    error_budget_exhausted: bool = False,
    widespread_customer_impact: bool = False,
) -> SeverityDecision:
    """Calculate an explainable incident severity decision."""

    normalised_severity = _normalise_reliability_severity(
        reliability_severity
    )
    normalised_environment = environment.strip().lower()
    normalised_alert_type = (
        _enum_value(alert_type).strip().upper()
        if alert_type is not None
        else None
    )
    normalised_criticality = (
        str(service_criticality).strip().upper()
        if service_criticality is not None
        else None
    )

    if affected_service_count < 0:
        raise ValueError("affected_service_count cannot be negative")

    if high_severity_alert_count < 0:
        raise ValueError(
            "high_severity_alert_count cannot be negative"
        )

    if availability_percent is not None:
        if not 0.0 <= availability_percent <= 100.0:
            raise ValueError(
                "availability_percent must be between 0 and 100"
            )

    latency_ratio: float | None = None

    if (
        normalised_alert_type == "LATENCY_BREACH"
        and measured_value is not None
        and threshold_value is not None
        and threshold_value > 0
    ):
        latency_ratio = measured_value / threshold_value

    evidence = {
        "alert_severity": normalised_severity.value,
        "alert_type": normalised_alert_type,
        "environment": normalised_environment,
        "service_criticality": normalised_criticality,
        "measured_value": measured_value,
        "threshold_value": threshold_value,
        "availability_percent": availability_percent,
        "affected_service_count": affected_service_count,
        "high_severity_alert_count": high_severity_alert_count,
        "deployment_correlated": deployment_correlated,
        "error_budget_exhausted": error_budget_exhausted,
        "widespread_customer_impact": widespread_customer_impact,
        "latency_ratio": latency_ratio,
    }

    if normalised_environment in NON_PRODUCTION_ENVIRONMENTS:
        return SeverityDecision(
            severity=IncidentSeverity.SEV_3,
            reason_code="NON_PRODUCTION_DEGRADATION",
            explanation=(
                f"The alert occurred in the non-production "
                f"environment {normalised_environment!r}."
            ),
            evidence=evidence,
        )

    if widespread_customer_impact:
        return SeverityDecision(
            severity=IncidentSeverity.SEV_1,
            reason_code="WIDESPREAD_CUSTOMER_IMPACT",
            explanation=(
                "The failure has widespread customer impact."
            ),
            evidence=evidence,
        )

    if (
        availability_percent is not None
        and availability_percent <= 0.0
    ):
        return SeverityDecision(
            severity=IncidentSeverity.SEV_1,
            reason_code="COMPLETE_SERVICE_UNAVAILABILITY",
            explanation="The service is completely unavailable.",
            evidence=evidence,
        )

    if (
        availability_percent is not None
        and availability_percent
        < INCIDENT_CRITICAL_AVAILABILITY_THRESHOLD
    ):
        return SeverityDecision(
            severity=IncidentSeverity.SEV_1,
            reason_code="CRITICAL_AVAILABILITY",
            explanation=(
                f"Availability {availability_percent:.2f}% is below "
                f"the critical threshold of "
                f"{INCIDENT_CRITICAL_AVAILABILITY_THRESHOLD:.2f}%."
            ),
            evidence=evidence,
        )

    if (
        affected_service_count
        >= INCIDENT_MULTIPLE_SERVICE_ESCALATION_COUNT
    ):
        return SeverityDecision(
            severity=IncidentSeverity.SEV_1,
            reason_code="MULTIPLE_SERVICES_AFFECTED",
            explanation=(
                f"{affected_service_count} related services are affected."
            ),
            evidence=evidence,
        )

    if (
        high_severity_alert_count
        >= INCIDENT_HIGH_SEVERITY_ALERT_ESCALATION_COUNT
    ):
        return SeverityDecision(
            severity=IncidentSeverity.SEV_1,
            reason_code="REPEATED_HIGH_SEVERITY_ALERTS",
            explanation=(
                f"{high_severity_alert_count} high-severity alerts "
                "are linked to the failure."
            ),
            evidence=evidence,
        )

    if normalised_severity == ReliabilitySeverity.CRITICAL:
        return SeverityDecision(
            severity=IncidentSeverity.SEV_1,
            reason_code="CRITICAL_RELIABILITY_ALERT",
            explanation=(
                "The reliability system classified the alert as critical."
            ),
            evidence=evidence,
        )

    if (
        error_budget_exhausted
        or normalised_alert_type == "ERROR_BUDGET_EXHAUSTED"
    ):
        return SeverityDecision(
            severity=IncidentSeverity.SEV_2,
            reason_code="ERROR_BUDGET_EXHAUSTED",
            explanation="The service error budget is exhausted.",
            evidence=evidence,
        )

    if (
        normalised_alert_type == "LATENCY_BREACH"
        and latency_ratio is not None
        and latency_ratio >= INCIDENT_CRITICAL_LATENCY_MULTIPLIER
    ):
        return SeverityDecision(
            severity=IncidentSeverity.SEV_2,
            reason_code="CRITICAL_LATENCY_BREACH",
            explanation=(
                f"Latency is {latency_ratio:.2f} times the configured "
                "SLO threshold."
            ),
            evidence=evidence,
        )

    if (
        deployment_correlated
        and normalised_severity == ReliabilitySeverity.HIGH
    ):
        return SeverityDecision(
            severity=IncidentSeverity.SEV_2,
            reason_code="DEPLOYMENT_CORRELATED_FAILURE",
            explanation=(
                "A high-severity production failure is correlated "
                "with a recent deployment."
            ),
            evidence=evidence,
        )

    if (
        normalised_criticality == "CRITICAL"
        and normalised_severity == ReliabilitySeverity.HIGH
    ):
        return SeverityDecision(
            severity=IncidentSeverity.SEV_2,
            reason_code="CRITICAL_SERVICE_DEGRADATION",
            explanation=(
                "A high-severity alert affects a critical "
                "production service."
            ),
            evidence=evidence,
        )

    calculated_severity = RELIABILITY_TO_INCIDENT_SEVERITY[
        normalised_severity
    ]

    return SeverityDecision(
        severity=calculated_severity,
        reason_code="RELIABILITY_SEVERITY_MAPPING",
        explanation=(
            f"Reliability severity {normalised_severity.value} maps "
            f"to incident severity {calculated_severity.value}."
        ),
        evidence=evidence,
    )


def calculate_incident_severity(
    reliability_severity: ReliabilitySeverity | str,
    *,
    environment: str = "production",
    alert_type: Any | None = None,
    service_criticality: str | None = None,
    measured_value: float | None = None,
    threshold_value: float | None = None,
    availability_percent: float | None = None,
    affected_service_count: int = 1,
    high_severity_alert_count: int = 0,
    deployment_correlated: bool = False,
    error_budget_exhausted: bool = False,
    widespread_customer_impact: bool = False,
) -> IncidentSeverity:
    """Compatibility wrapper returning only the severity enum."""

    return calculate_incident_severity_decision(
        reliability_severity,
        environment=environment,
        alert_type=alert_type,
        service_criticality=service_criticality,
        measured_value=measured_value,
        threshold_value=threshold_value,
        availability_percent=availability_percent,
        affected_service_count=affected_service_count,
        high_severity_alert_count=high_severity_alert_count,
        deployment_correlated=deployment_correlated,
        error_budget_exhausted=error_budget_exhausted,
        widespread_customer_impact=widespread_customer_impact,
    ).severity


def should_escalate_severity(
    *,
    affected_service_count: int = 1,
    availability_percent: float | None = None,
    high_severity_alert_count: int = 0,
) -> bool:
    """Compatibility helper for contextual SEV-1 escalation."""

    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.LOW,
        environment="production",
        affected_service_count=affected_service_count,
        availability_percent=availability_percent,
        high_severity_alert_count=high_severity_alert_count,
    )

    return decision.severity == IncidentSeverity.SEV_1
