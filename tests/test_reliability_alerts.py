from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.models import (
    ErrorBudgetState,
    ReliabilityAlertStatus,
    ReliabilityAlertType,
    ReliabilitySeverity,
    SLOMetricType,
)
from app.reliability import alert_service


def build_breach_context():
    service = SimpleNamespace(
        id="service-payment-1",
        name="payment-service",
    )

    slo_definition = SimpleNamespace(
        id="slo-availability-1",
        service_id=service.id,
        metric_type=SLOMetricType.AVAILABILITY,
        target_value=99.9,
        window_minutes=60,
        severity_on_breach=ReliabilitySeverity.HIGH,
        environment_id=None,
    )

    measurement = SimpleNamespace(
        id="measurement-1",
        slo_definition_id=slo_definition.id,
        service_id=service.id,
        metric_type=SLOMetricType.AVAILABILITY,
        measured_value=99.5,
        target_value=99.9,
        is_breached=True,
        window_minutes=60,
    )

    error_budget = SimpleNamespace(
        status=ErrorBudgetState.EXHAUSTED,
        allowed_failure_percentage=0.1,
        actual_failure_percentage=0.5,
        consumed_percentage=500.0,
        remaining_percentage=0.0,
        burn_rate=5.0,
        rapid_burn=True,
    )

    return (
        service,
        slo_definition,
        measurement,
        error_budget,
    )


def install_alert_dependencies(
    monkeypatch,
    *,
    latest_deployment,
):
    captured_event = {}
    generated_event = SimpleNamespace(
        event_id="evt-reliability-test",
    )

    monkeypatch.setattr(
        alert_service,
        "find_existing_open_alert",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        alert_service,
        "_find_latest_deployment",
        lambda *args, **kwargs: latest_deployment,
    )

    monkeypatch.setattr(
        alert_service,
        "get_deployment_environment",
        lambda *args, **kwargs: "staging",
    )

    def fake_record_platform_event(*args, **kwargs):
        captured_event.update(kwargs)
        return generated_event

    monkeypatch.setattr(
        alert_service,
        "record_platform_event",
        fake_record_platform_event,
    )

    return captured_event, generated_event


def test_alert_and_event_are_generated_for_slo_breach(
    monkeypatch,
):
    db = MagicMock()

    deployment = SimpleNamespace(
        id=uuid4(),
        environment_id=None,
    )

    (
        service,
        slo_definition,
        measurement,
        error_budget,
    ) = build_breach_context()

    (
        captured_event,
        generated_event,
    ) = install_alert_dependencies(
        monkeypatch,
        latest_deployment=deployment,
    )

    (
        alert,
        event,
        alert_created,
    ) = alert_service.create_reliability_alert_and_event(
        db=db,
        service=service,
        slo_definition=slo_definition,
        measurement=measurement,
        error_budget=error_budget,
    )

    assert alert_created is True
    assert alert is not None
    assert event is generated_event

    assert (
        alert.alert_type
        == ReliabilityAlertType.ERROR_BUDGET_EXHAUSTED
    )
    assert alert.severity == ReliabilitySeverity.HIGH
    assert alert.status == ReliabilityAlertStatus.OPEN

    assert alert.triggered_value == 99.5
    assert alert.threshold_value == 99.9

    db.add.assert_called_once_with(alert)
    db.flush.assert_called()

    assert captured_event["service_id"] == service.id
    assert captured_event["environment"] == "staging"

    assert captured_event["correlation_id"] == (
        "service-payment-1:staging:AVAILABILITY"
    )

    payload = captured_event["payload"]

    assert payload["severity"] == "HIGH"
    assert payload["service_name"] == "payment-service"
    assert payload["source"] == "platformiq-reliability"
    assert payload["metric_type"] == "AVAILABILITY"
    assert payload["is_breached"] is True
    assert payload["triggered_value"] == 99.5
    assert payload["threshold_value"] == 99.9
    assert payload["error_budget_remaining"] == 0.0
    assert payload["error_budget_consumed"] == 500.0


def test_alert_is_linked_to_latest_deployment(
    monkeypatch,
):
    db = MagicMock()

    latest_deployment = SimpleNamespace(
        id=uuid4(),
        environment_id=None,
    )

    (
        service,
        slo_definition,
        measurement,
        error_budget,
    ) = build_breach_context()

    deployment_lookup = {}
    captured_event = {}

    monkeypatch.setattr(
        alert_service,
        "find_existing_open_alert",
        lambda *args, **kwargs: None,
    )

    def fake_find_latest_deployment(
        *args,
        **kwargs,
    ):
        deployment_lookup.update(kwargs)
        return latest_deployment

    monkeypatch.setattr(
        alert_service,
        "_find_latest_deployment",
        fake_find_latest_deployment,
    )

    monkeypatch.setattr(
        alert_service,
        "get_deployment_environment",
        lambda *args, **kwargs: "staging",
    )

    def fake_record_platform_event(*args, **kwargs):
        captured_event.update(kwargs)

        return SimpleNamespace(
            event_id="evt-deployment-link-test",
        )

    monkeypatch.setattr(
        alert_service,
        "record_platform_event",
        fake_record_platform_event,
    )

    (
        alert,
        _event,
        alert_created,
    ) = alert_service.create_reliability_alert_and_event(
        db=db,
        service=service,
        slo_definition=slo_definition,
        measurement=measurement,
        error_budget=error_budget,
    )

    assert alert_created is True
    assert alert.deployment_id == latest_deployment.id

    assert (
        captured_event["payload"]["deployment_id"]
        == str(latest_deployment.id)
    )

    assert deployment_lookup["service_id"] == service.id
    assert deployment_lookup["occurred_at"] is not None
