"""Integration tests for Sprint 7F incident metric snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incidents.service import (
    create_or_update_incident_from_alert,
    get_incident_detail,
)
from app.models import (
    ErrorBudgetState,
    ErrorBudgetStatus,
    IncidentMetric,
    Project,
    ReliabilityAlert,
    ReliabilityAlertStatus,
    ReliabilityAlertType,
    ReliabilitySeverity,
    Service,
    SLODefinition,
    SLOMeasurement,
    SLOMetricType,
)


def _create_service_and_slos(
    db: Session,
) -> tuple[Service, dict[SLOMetricType, SLODefinition]]:
    project = Project(
        id=str(uuid4()),
        name=f"Sprint 7F Snapshot Project {uuid4()}",
    )
    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name="payment-service",
        service_type="backend",
        owner="platform-team",
    )

    availability_slo = SLODefinition(
        id=str(uuid4()),
        service_id=service.id,
        metric_type=SLOMetricType.AVAILABILITY,
        target_value=99.9,
        window_minutes=60,
        severity_on_breach=ReliabilitySeverity.HIGH,
        enabled=True,
    )
    latency_slo = SLODefinition(
        id=str(uuid4()),
        service_id=service.id,
        metric_type=SLOMetricType.P95_LATENCY,
        target_value=500.0,
        window_minutes=60,
        severity_on_breach=ReliabilitySeverity.HIGH,
        enabled=True,
    )
    error_rate_slo = SLODefinition(
        id=str(uuid4()),
        service_id=service.id,
        metric_type=SLOMetricType.ERROR_RATE,
        target_value=1.0,
        window_minutes=60,
        severity_on_breach=ReliabilitySeverity.HIGH,
        enabled=True,
    )

    db.add_all(
        [
            project,
            service,
            availability_slo,
            latency_slo,
            error_rate_slo,
        ]
    )
    db.flush()

    return service, {
        SLOMetricType.AVAILABILITY: availability_slo,
        SLOMetricType.P95_LATENCY: latency_slo,
        SLOMetricType.ERROR_RATE: error_rate_slo,
    }


def _create_measurement(
    db: Session,
    *,
    service: Service,
    slo: SLODefinition,
    measured_value: float,
    target_value: float,
    is_breached: bool,
    evaluated_at: datetime,
    source: str = "PROMETHEUS",
) -> SLOMeasurement:
    measurement = SLOMeasurement(
        id=str(uuid4()),
        slo_definition_id=slo.id,
        service_id=service.id,
        metric_type=slo.metric_type,
        measured_value=measured_value,
        target_value=target_value,
        is_breached=is_breached,
        window_minutes=slo.window_minutes,
        source=source,
        evaluated_at=evaluated_at,
    )

    db.add(measurement)
    db.flush()

    return measurement


def _create_error_budget(
    db: Session,
    *,
    service: Service,
    slo: SLODefinition,
    evaluated_at: datetime,
    status: ErrorBudgetState,
    consumed_percentage: float,
    remaining_percentage: float,
    burn_rate: float,
) -> ErrorBudgetStatus:
    error_budget = ErrorBudgetStatus(
        id=str(uuid4()),
        slo_definition_id=slo.id,
        service_id=service.id,
        target_percentage=99.9,
        allowed_failure_percentage=0.1,
        consumed_percentage=consumed_percentage,
        remaining_percentage=remaining_percentage,
        burn_rate=burn_rate,
        status=status,
        window_minutes=60,
        evaluated_at=evaluated_at,
    )

    db.add(error_budget)
    db.flush()

    return error_budget


def _create_alert(
    db: Session,
    *,
    service: Service,
    slo: SLODefinition,
    created_at: datetime,
) -> ReliabilityAlert:
    alert = ReliabilityAlert(
        id=str(uuid4()),
        service_id=service.id,
        slo_definition_id=slo.id,
        alert_type=ReliabilityAlertType.AVAILABILITY_BREACH,
        severity=ReliabilitySeverity.HIGH,
        triggered_value=94.5,
        threshold_value=99.9,
        status=ReliabilityAlertStatus.OPEN,
        created_at=created_at,
    )

    db.add(alert)
    db.flush()
    db.refresh(alert)

    return alert


def _get_metrics(
    db: Session,
    *,
    incident_id,
) -> list[IncidentMetric]:
    statement = (
        select(IncidentMetric)
        .where(
            IncidentMetric.incident_id == incident_id,
        )
        .order_by(
            IncidentMetric.metric_type,
            IncidentMetric.metric_name,
        )
    )

    return list(
        db.execute(statement).scalars().all(),
    )


def _metric_map(
    metrics: list[IncidentMetric],
) -> dict[tuple[str, str], IncidentMetric]:
    return {
        (metric.metric_type, metric.metric_name): metric
        for metric in metrics
    }


def test_captures_historical_reliability_snapshot(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service, slos = _create_service_and_slos(db_session)

    availability = _create_measurement(
        db_session,
        service=service,
        slo=slos[SLOMetricType.AVAILABILITY],
        measured_value=98.7,
        target_value=99.9,
        is_breached=True,
        evaluated_at=detected_at - timedelta(minutes=10),
    )
    _create_measurement(
        db_session,
        service=service,
        slo=slos[SLOMetricType.P95_LATENCY],
        measured_value=780.0,
        target_value=500.0,
        is_breached=True,
        evaluated_at=detected_at - timedelta(minutes=8),
    )
    _create_measurement(
        db_session,
        service=service,
        slo=slos[SLOMetricType.ERROR_RATE],
        measured_value=3.2,
        target_value=1.0,
        is_breached=True,
        evaluated_at=detected_at - timedelta(minutes=6),
    )

    # This newer value is after incident detection and must be ignored.
    future_availability = _create_measurement(
        db_session,
        service=service,
        slo=slos[SLOMetricType.AVAILABILITY],
        measured_value=50.0,
        target_value=99.9,
        is_breached=True,
        evaluated_at=detected_at + timedelta(minutes=2),
    )

    historical_budget = _create_error_budget(
        db_session,
        service=service,
        slo=slos[SLOMetricType.AVAILABILITY],
        evaluated_at=detected_at - timedelta(minutes=5),
        status=ErrorBudgetState.EXHAUSTED,
        consumed_percentage=500.0,
        remaining_percentage=0.0,
        burn_rate=5.0,
    )

    # This future budget must also be ignored.
    _create_error_budget(
        db_session,
        service=service,
        slo=slos[SLOMetricType.AVAILABILITY],
        evaluated_at=detected_at + timedelta(minutes=3),
        status=ErrorBudgetState.HEALTHY,
        consumed_percentage=0.0,
        remaining_percentage=100.0,
        burn_rate=0.0,
    )

    alert = _create_alert(
        db_session,
        service=service,
        slo=slos[SLOMetricType.AVAILABILITY],
        created_at=detected_at,
    )

    result = create_or_update_incident_from_alert(
        db_session,
        alert,
        environment="production",
    )

    metrics = _get_metrics(
        db_session,
        incident_id=result.incident.incident_id,
    )
    metric_map = _metric_map(metrics)

    # Two alert values, three SLO measurements and one error-budget row.
    assert len(metrics) == 6

    availability_snapshot = metric_map[
        ("SLO_MEASUREMENT", "AVAILABILITY")
    ]
    latency_snapshot = metric_map[
        ("SLO_MEASUREMENT", "P95_LATENCY")
    ]
    error_rate_snapshot = metric_map[
        ("SLO_MEASUREMENT", "ERROR_RATE")
    ]
    budget_snapshot = metric_map[
        ("ERROR_BUDGET", "remaining_percentage")
    ]

    assert availability_snapshot.value == pytest.approx(98.7)
    assert availability_snapshot.unit == "%"
    assert (
        availability_snapshot.metadata_json["measurement_id"]
        == availability.id
    )
    assert (
        availability_snapshot.metadata_json["measurement_id"]
        != future_availability.id
    )
    assert availability_snapshot.metadata_json[
        "target_value"
    ] == pytest.approx(99.9)
    assert availability_snapshot.metadata_json["is_breached"] is True
    assert availability_snapshot.source == "PROMETHEUS"

    assert latency_snapshot.value == pytest.approx(780.0)
    assert latency_snapshot.unit == "ms"
    assert latency_snapshot.metadata_json[
        "target_value"
    ] == pytest.approx(500.0)

    assert error_rate_snapshot.value == pytest.approx(3.2)
    assert error_rate_snapshot.unit == "%"
    assert error_rate_snapshot.metadata_json[
        "target_value"
    ] == pytest.approx(1.0)

    assert budget_snapshot.value == pytest.approx(0.0)
    assert budget_snapshot.unit == "%"
    assert (
        budget_snapshot.metadata_json["error_budget_status_id"]
        == historical_budget.id
    )
    assert budget_snapshot.metadata_json["status"] == "EXHAUSTED"
    assert budget_snapshot.metadata_json[
        "consumed_percentage"
    ] == pytest.approx(500.0)
    assert budget_snapshot.metadata_json["burn_rate"] == pytest.approx(
        5.0
    )


def test_later_evaluations_do_not_change_incident_snapshot(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service, slos = _create_service_and_slos(db_session)
    availability_slo = slos[SLOMetricType.AVAILABILITY]

    _create_measurement(
        db_session,
        service=service,
        slo=availability_slo,
        measured_value=98.5,
        target_value=99.9,
        is_breached=True,
        evaluated_at=detected_at - timedelta(minutes=2),
    )
    _create_error_budget(
        db_session,
        service=service,
        slo=availability_slo,
        evaluated_at=detected_at - timedelta(minutes=1),
        status=ErrorBudgetState.EXHAUSTED,
        consumed_percentage=300.0,
        remaining_percentage=0.0,
        burn_rate=3.0,
    )

    alert = _create_alert(
        db_session,
        service=service,
        slo=availability_slo,
        created_at=detected_at,
    )

    result = create_or_update_incident_from_alert(
        db_session,
        alert,
        environment="production",
    )
    incident_id = result.incident.incident_id

    initial_metrics = _get_metrics(
        db_session,
        incident_id=incident_id,
    )
    initial_metric_ids = {
        metric.id
        for metric in initial_metrics
    }

    assert len(initial_metrics) == 4

    # Insert newer reliability evaluations after incident creation.
    _create_measurement(
        db_session,
        service=service,
        slo=availability_slo,
        measured_value=100.0,
        target_value=99.9,
        is_breached=False,
        evaluated_at=detected_at + timedelta(minutes=5),
    )
    _create_error_budget(
        db_session,
        service=service,
        slo=availability_slo,
        evaluated_at=detected_at + timedelta(minutes=5),
        status=ErrorBudgetState.HEALTHY,
        consumed_percentage=0.0,
        remaining_percentage=100.0,
        burn_rate=0.0,
    )
    db_session.commit()

    detail = get_incident_detail(
        db_session,
        incident_id,
    )

    assert detail is not None

    snapshot_map = {
        (metric.metric_type, metric.metric_name): metric
        for metric in detail.metric_snapshot
    }

    assert len(detail.metric_snapshot) == 4
    assert snapshot_map[
        ("SLO_MEASUREMENT", "AVAILABILITY")
    ].value == pytest.approx(98.5)
    assert snapshot_map[
        ("ERROR_BUDGET", "remaining_percentage")
    ].value == pytest.approx(0.0)
    assert snapshot_map[
        ("ERROR_BUDGET", "remaining_percentage")
    ].metadata_json["status"] == "EXHAUSTED"

    # Reprocessing the same alert must not duplicate snapshot rows.
    repeated = create_or_update_incident_from_alert(
        db_session,
        alert,
        environment="production",
    )

    assert repeated.incident.incident_id == incident_id

    final_metrics = _get_metrics(
        db_session,
        incident_id=incident_id,
    )

    assert len(final_metrics) == 4
    assert {
        metric.id
        for metric in final_metrics
    } == initial_metric_ids


def test_incident_remains_valid_without_reliability_history(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service, slos = _create_service_and_slos(db_session)

    alert = _create_alert(
        db_session,
        service=service,
        slo=slos[SLOMetricType.AVAILABILITY],
        created_at=detected_at,
    )

    result = create_or_update_incident_from_alert(
        db_session,
        alert,
        environment="production",
    )

    metrics = _get_metrics(
        db_session,
        incident_id=result.incident.incident_id,
    )

    assert result.incident.incident_id is not None
    assert result.suspected_deployment is None
    assert len(metrics) == 2
    assert {
        metric.metric_type
        for metric in metrics
    } == {"RELIABILITY_ALERT"}
