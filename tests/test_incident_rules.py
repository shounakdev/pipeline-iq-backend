"""Tests for Sprint 7E incident deduplication and severity rules."""

from app.incidents.rules import (
    build_deduplication_key,
    build_deduplication_lock_id,
    calculate_incident_severity,
    calculate_incident_severity_decision,
    is_more_severe,
)
from app.models import IncidentSeverity, ReliabilitySeverity


def test_build_deduplication_key_normalises_values() -> None:
    key = build_deduplication_key(
        service_id="SERVICE-123",
        environment=" Production ",
        slo_or_alert_category="SLO:Availability",
    )

    assert key == "service-123:production:slo-availability"


def test_high_production_alert_maps_to_sev_2() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="production",
    )

    assert decision.severity == IncidentSeverity.SEV_2
    assert decision.reason_code == "RELIABILITY_SEVERITY_MAPPING"
    assert decision.evidence["environment"] == "production"


def test_non_production_alert_maps_to_sev_3() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="staging",
    )

    assert decision.severity == IncidentSeverity.SEV_3
    assert decision.reason_code == "NON_PRODUCTION_DEGRADATION"


def test_critical_availability_maps_to_sev_1() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="production",
        alert_type="AVAILABILITY_BREACH",
        availability_percent=94.9,
        measured_value=94.9,
        threshold_value=99.9,
    )

    assert decision.severity == IncidentSeverity.SEV_1
    assert decision.reason_code == "CRITICAL_AVAILABILITY"
    assert decision.evidence["availability_percent"] == 94.9


def test_availability_at_critical_boundary_does_not_force_sev_1() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="production",
        alert_type="AVAILABILITY_BREACH",
        availability_percent=95.0,
    )

    assert decision.severity == IncidentSeverity.SEV_2


def test_complete_unavailability_maps_to_sev_1() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="production",
        alert_type="AVAILABILITY_BREACH",
        availability_percent=0.0,
    )

    assert decision.severity == IncidentSeverity.SEV_1
    assert decision.reason_code == "COMPLETE_SERVICE_UNAVAILABILITY"


def test_multiple_related_services_map_to_sev_1() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="production",
        affected_service_count=2,
    )

    assert decision.severity == IncidentSeverity.SEV_1
    assert decision.reason_code == "MULTIPLE_SERVICES_AFFECTED"


def test_repeated_high_severity_alerts_map_to_sev_1() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="production",
        high_severity_alert_count=3,
    )

    assert decision.severity == IncidentSeverity.SEV_1
    assert decision.reason_code == "REPEATED_HIGH_SEVERITY_ALERTS"


def test_error_budget_exhaustion_maps_to_sev_2() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.MEDIUM,
        environment="production",
        alert_type="ERROR_BUDGET_EXHAUSTED",
        error_budget_exhausted=True,
    )

    assert decision.severity == IncidentSeverity.SEV_2
    assert decision.reason_code == "ERROR_BUDGET_EXHAUSTED"


def test_critical_latency_ratio_maps_to_sev_2() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.MEDIUM,
        environment="production",
        alert_type="LATENCY_BREACH",
        measured_value=1200.0,
        threshold_value=500.0,
    )

    assert decision.severity == IncidentSeverity.SEV_2
    assert decision.reason_code == "CRITICAL_LATENCY_BREACH"
    assert decision.evidence["latency_ratio"] == 2.4


def test_high_alert_on_critical_service_maps_to_sev_2() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="production",
        service_criticality="CRITICAL",
    )

    assert decision.severity == IncidentSeverity.SEV_2
    assert decision.reason_code == "CRITICAL_SERVICE_DEGRADATION"


def test_deployment_correlated_high_alert_maps_to_sev_2() -> None:
    decision = calculate_incident_severity_decision(
        ReliabilitySeverity.HIGH,
        environment="production",
        deployment_correlated=True,
    )

    assert decision.severity == IncidentSeverity.SEV_2
    assert decision.reason_code == "DEPLOYMENT_CORRELATED_FAILURE"


def test_severity_comparison_allows_only_upward_escalation() -> None:
    assert is_more_severe(
        IncidentSeverity.SEV_2,
        IncidentSeverity.SEV_3,
    )
    assert is_more_severe(
        IncidentSeverity.SEV_1,
        IncidentSeverity.SEV_2,
    )

    assert not is_more_severe(
        IncidentSeverity.SEV_3,
        IncidentSeverity.SEV_2,
    )
    assert not is_more_severe(
        IncidentSeverity.SEV_2,
        IncidentSeverity.SEV_2,
    )


def test_compatibility_wrapper_returns_enum() -> None:
    severity = calculate_incident_severity(
        ReliabilitySeverity.HIGH,
        environment="production",
    )

    assert severity == IncidentSeverity.SEV_2

def test_deduplication_lock_id_is_stable_and_signed_64_bit() -> None:
    first = build_deduplication_lock_id(
        "service-1:production:slo-1",
    )
    repeated = build_deduplication_lock_id(
        "service-1:production:slo-1",
    )
    different = build_deduplication_lock_id(
        "service-1:production:slo-2",
    )

    assert first == repeated
    assert first != different
    assert -(2**63) <= first <= (2**63 - 1)

