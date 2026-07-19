from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.incidents import service as incident_service
from app.incidents.metrics import (
    calculate_incident_metrics,
    format_duration,
)


def test_incident_metrics_use_timezone_aware_timestamps():
    india_timezone = timezone(
        timedelta(hours=5, minutes=30)
    )

    failure_started_at = datetime(
        2026,
        7,
        19,
        10,
        0,
        tzinfo=india_timezone,
    )

    # 10:01 IST
    detected_at = datetime(
        2026,
        7,
        19,
        4,
        31,
        tzinfo=timezone.utc,
    )

    # Two minutes after detection
    acknowledged_at = datetime(
        2026,
        7,
        19,
        4,
        33,
        tzinfo=timezone.utc,
    )

    # Thirty-two minutes after detection
    resolved_at = datetime(
        2026,
        7,
        19,
        5,
        3,
        tzinfo=timezone.utc,
    )

    metrics = calculate_incident_metrics(
        failure_started_at=failure_started_at,
        detected_at=detected_at,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
    )

    assert metrics == {
        "mttd_seconds": 60,
        "mtta_seconds": 120,
        "mttr_seconds": 1920,
        "mttd_display": "1m",
        "mtta_display": "2m",
        "mttr_display": "32m",
    }


def test_mttd_is_null_when_failure_start_is_missing():
    detected_at = datetime.now(timezone.utc)

    metrics = calculate_incident_metrics(
        failure_started_at=None,
        detected_at=detected_at,
        acknowledged_at=None,
        resolved_at=None,
    )

    assert metrics["mttd_seconds"] is None
    assert metrics["mttd_display"] is None


def test_mtta_is_null_before_acknowledgement():
    detected_at = datetime.now(timezone.utc)

    metrics = calculate_incident_metrics(
        failure_started_at=None,
        detected_at=detected_at,
        acknowledged_at=None,
        resolved_at=None,
    )

    assert metrics["mtta_seconds"] is None
    assert metrics["mtta_display"] is None


def test_mttr_is_null_before_resolution():
    detected_at = datetime.now(timezone.utc)

    metrics = calculate_incident_metrics(
        failure_started_at=None,
        detected_at=detected_at,
        acknowledged_at=None,
        resolved_at=None,
    )

    assert metrics["mttr_seconds"] is None
    assert metrics["mttr_display"] is None


def test_missing_detected_at_produces_null_metrics():
    metrics = calculate_incident_metrics(
        failure_started_at=datetime.now(timezone.utc),
        detected_at=None,
        acknowledged_at=datetime.now(timezone.utc),
        resolved_at=datetime.now(timezone.utc),
    )

    assert metrics["mttd_seconds"] is None
    assert metrics["mtta_seconds"] is None
    assert metrics["mttr_seconds"] is None


def test_negative_duration_is_not_reported_as_zero():
    detected_at = datetime.now(timezone.utc)
    failure_started_at = detected_at + timedelta(minutes=1)

    metrics = calculate_incident_metrics(
        failure_started_at=failure_started_at,
        detected_at=detected_at,
        acknowledged_at=None,
        resolved_at=None,
    )

    assert metrics["mttd_seconds"] is None
    assert metrics["mttd_display"] is None


def test_format_duration():
    assert format_duration(None) is None
    assert format_duration(0) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(60) == "1m"
    assert format_duration(120) == "2m"
    assert format_duration(1920) == "32m"
    assert format_duration(3660) == "1h 1m"
    assert format_duration(90_000) == "1d 1h"


def test_aggregate_averages_exclude_missing_timestamps(
    monkeypatch,
):
    detected_at = datetime(
        2026,
        7,
        19,
        10,
        0,
        tzinfo=timezone.utc,
    )

    incidents = [
        SimpleNamespace(
            failure_started_at=(
                detected_at - timedelta(seconds=60)
            ),
            detected_at=detected_at,
            acknowledged_at=(
                detected_at + timedelta(seconds=120)
            ),
            resolved_at=(
                detected_at + timedelta(seconds=1920)
            ),
            status="RESOLVED",
            severity="SEV-2",
        ),
        SimpleNamespace(
            failure_started_at=None,
            detected_at=detected_at,
            acknowledged_at=None,
            resolved_at=None,
            status="DETECTED",
            severity="SEV-1",
        ),
    ]

    monkeypatch.setattr(
        incident_service.repository,
        "get_incidents_for_metrics",
        lambda db: incidents,
    )

    result = incident_service.get_incident_metrics_summary(
        db=object(),
    )

    assert result.average_mttd_seconds == 60
    assert result.average_mtta_seconds == 120
    assert result.average_mttr_seconds == 1920

    assert result.average_mttd_display == "1m"
    assert result.average_mtta_display == "2m"
    assert result.average_mttr_display == "32m"

    assert result.open_incident_count == 1
    assert result.resolved_incident_count == 1

    assert result.sev_1_incident_count == 1
    assert result.sev_2_incident_count == 1
    assert result.sev_3_incident_count == 0