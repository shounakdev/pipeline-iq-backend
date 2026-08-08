from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.chaos.config import ChaosSettings
from app.chaos.services.benchmark_service import calculate_benchmark
from app.models import (
    BenchmarkStatus,
    ChaosObservationType,
    DiagnosisRating,
    RCAReportStatus,
)


BASE_TIME = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def _settings(**overrides):
    values = {
        "enabled": True,
        "allowed_environments": frozenset({"staging"}),
        "allowed_namespaces": frozenset({"platformiq-staging"}),
        "allowed_services": frozenset(),
        "max_duration_seconds": 600,
        "max_concurrent_runs": 1,
        "watchdog_interval_seconds": 30,
        "max_detection_seconds": 30,
        "max_alert_seconds": 60,
        "max_incident_seconds": 90,
        "max_diagnosis_seconds": 180,
        "max_recovery_seconds": 600,
    }
    values.update(overrides)
    return ChaosSettings(**values)


def _observation(kind, seconds, **details):
    return SimpleNamespace(
        observation_type=kind,
        observed_at=BASE_TIME + timedelta(seconds=seconds),
        details=details,
    )


def _successful_run():
    report = SimpleNamespace(
        status=RCAReportStatus.COMPLETED,
        generated_at=BASE_TIME + timedelta(seconds=100),
        report_json={"root_cause_category": "KUBERNETES"},
    )
    return SimpleNamespace(
        id=uuid4(),
        failure_injected_at=BASE_TIME,
        experiment=SimpleNamespace(
            expected_behavior={"expected_root_cause": "KUBERNETES"}
        ),
        rca_report=report,
        remediation=None,
        remediation_execution=None,
        recovery_verification=None,
    )


def _successful_observations():
    return [
        _observation(ChaosObservationType.FAILURE_INJECTED, 0),
        _observation(ChaosObservationType.TELEMETRY_ANOMALY, 10),
        _observation(ChaosObservationType.ALERT_CREATED, 20),
        _observation(ChaosObservationType.INCIDENT_CREATED, 30),
        _observation(ChaosObservationType.RCA_COMPLETED, 100),
        _observation(ChaosObservationType.REMEDIATION_RECOMMENDED, 110),
        _observation(
            ChaosObservationType.REMEDIATION_APPROVED,
            125,
            decision="APPROVED",
        ),
        _observation(
            ChaosObservationType.REMEDIATION_EXECUTED,
            140,
            status="SUCCEEDED",
        ),
        _observation(
            ChaosObservationType.RECOVERY_COMPLETED,
            150,
            recovery_succeeded=True,
        ),
    ]


def _calculate(monkeypatch, run=None, observations=None, settings=None):
    captured = {}
    monkeypatch.setattr(
        "app.chaos.services.benchmark_service.repository.list_observations_for_run",
        lambda db, run_id: (
            observations
            if observations is not None
            else _successful_observations()
        ),
    )

    def save_benchmark(db, *, chaos_run_id, values):
        captured.update(values)
        return SimpleNamespace(**values)

    monkeypatch.setattr(
        "app.chaos.services.benchmark_service.repository.save_benchmark",
        save_benchmark,
    )
    result = calculate_benchmark(
        FakeSession(),
        run or _successful_run(),
        settings=settings or _settings(),
        calculated_at=BASE_TIME + timedelta(minutes=20),
    )
    return result, captured


def test_every_duration_is_calculated_from_its_defined_anchors(monkeypatch):
    benchmark, _ = _calculate(monkeypatch)

    assert benchmark.time_to_detect_ms == 10_000
    assert benchmark.time_to_alert_ms == 20_000
    assert benchmark.time_to_incident_ms == 30_000
    assert benchmark.time_to_diagnose_ms == 70_000
    assert benchmark.time_to_approve_ms == 15_000
    assert benchmark.time_to_recover_ms == 150_000


def test_missing_timestamp_produces_incomplete(monkeypatch):
    observations = [
        item
        for item in _successful_observations()
        if item.observation_type != ChaosObservationType.ALERT_CREATED
    ]
    benchmark, _ = _calculate(monkeypatch, observations=observations)
    assert benchmark.benchmark_status == BenchmarkStatus.INCOMPLETE


def test_negative_timestamp_is_rejected(monkeypatch):
    observations = _successful_observations()
    observations[1].observed_at = BASE_TIME - timedelta(seconds=1)
    with pytest.raises(ValueError, match="time to detect cannot be negative"):
        _calculate(monkeypatch, observations=observations)


def test_incorrect_diagnosis_fails_benchmark(monkeypatch):
    run = _successful_run()
    run.rca_report.report_json["root_cause_category"] = "APPLICATION_ERROR"
    benchmark, _ = _calculate(monkeypatch, run=run)
    assert benchmark.diagnosis_rating == DiagnosisRating.INCORRECT
    assert benchmark.benchmark_status == BenchmarkStatus.FAILED


def test_related_diagnosis_is_partially_correct(monkeypatch):
    run = _successful_run()
    run.experiment.expected_behavior["expected_root_cause"] = "KUBERNETES_RUNTIME"
    benchmark, _ = _calculate(monkeypatch, run=run)
    assert benchmark.diagnosis_rating == DiagnosisRating.PARTIALLY_CORRECT
    assert benchmark.benchmark_status == BenchmarkStatus.PASSED


def test_failed_recovery_fails_benchmark(monkeypatch):
    observations = _successful_observations()
    observations[-1].details["recovery_succeeded"] = False
    benchmark, _ = _calculate(monkeypatch, observations=observations)
    assert benchmark.recovery_succeeded is False
    assert benchmark.benchmark_status == BenchmarkStatus.FAILED


def test_successful_run_passes_benchmark(monkeypatch):
    benchmark, _ = _calculate(monkeypatch)
    assert benchmark.diagnosis_rating == DiagnosisRating.CORRECT
    assert benchmark.benchmark_status == BenchmarkStatus.PASSED


def test_threshold_breach_fails_benchmark(monkeypatch):
    benchmark, _ = _calculate(
        monkeypatch,
        settings=_settings(max_detection_seconds=9),
    )
    assert benchmark.benchmark_status == BenchmarkStatus.FAILED


def test_thresholds_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("CHAOS_MAX_DETECTION_SECONDS", "11")
    monkeypatch.setenv("CHAOS_MAX_ALERT_SECONDS", "22")
    monkeypatch.setenv("CHAOS_MAX_INCIDENT_SECONDS", "33")
    monkeypatch.setenv("CHAOS_MAX_DIAGNOSIS_SECONDS", "44")
    monkeypatch.setenv("CHAOS_MAX_RECOVERY_SECONDS", "55")
    settings = ChaosSettings.from_env()
    assert (
        settings.max_detection_seconds,
        settings.max_alert_seconds,
        settings.max_incident_seconds,
        settings.max_diagnosis_seconds,
        settings.max_recovery_seconds,
    ) == (11, 22, 33, 44, 55)