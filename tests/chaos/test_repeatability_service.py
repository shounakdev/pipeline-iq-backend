from types import SimpleNamespace

import pytest

from app.chaos.adapters.mock_adapter import MockChaosAdapter
from app.chaos.scenarios import SCENARIO_TYPES
from app.chaos.services.repeatability_service import summarize_repeatability
from app.models import BenchmarkStatus, DiagnosisRating


def _run(scenario_type, repetition, *, status=BenchmarkStatus.PASSED):
    return SimpleNamespace(
        id=f"{scenario_type.value.lower()}-{repetition}",
        experiment=SimpleNamespace(scenario_type=scenario_type),
        benchmark=SimpleNamespace(
            benchmark_status=status,
            detection_succeeded=True,
            time_to_incident_ms=30_000 + repetition * 1_000,
            diagnosis_rating=DiagnosisRating.CORRECT,
            recovery_succeeded=True,
            time_to_detect_ms=10_000 + repetition * 1_000,
            time_to_recover_ms=120_000 + repetition * 3_000,
        ),
    )


def test_all_five_scenarios_are_repeatable_across_three_runs():
    runs = []
    for scenario_type, scenario_class in SCENARIO_TYPES.items():
        for repetition in range(3):
            scenario = scenario_class("platformiq-staging")
            adapter = MockChaosAdapter()
            resource = scenario.inject(
                adapter,
                run_id=f"{scenario_type.value.lower()}-{repetition}",
            )
            assert scenario.cleanup(adapter, resource) is True
            assert adapter.resources == {}
            runs.append(_run(scenario_type, repetition))

    report = summarize_repeatability(runs)

    assert report["total_executions"] == 15
    assert report["minimum_runs_per_scenario_met"] is True
    assert {item["scenario_type"] for item in report["scenarios"]} == {
        item.value for item in SCENARIO_TYPES
    }
    for result in report["scenarios"]:
        assert result["executions"] == 3
        assert result["detection_success_rate"] == 100.0
        assert result["incident_creation_success_rate"] == 100.0
        assert result["rca_correctness_rate"] == 100.0
        assert result["recovery_success_rate"] == 100.0
        assert result["detection_time"] == {
            "average_ms": 11_000.0,
            "maximum_ms": 12_000,
            "variance_ms2": pytest.approx(666_666.67),
        }
        assert result["recovery_time"] == {
            "average_ms": 123_000.0,
            "maximum_ms": 126_000,
            "variance_ms2": 6_000_000.0,
        }
        assert result["failed_or_incomplete_runs"] == []


def test_failed_and_incomplete_runs_reduce_rates_and_are_listed():
    scenario_type = next(iter(SCENARIO_TYPES))
    runs = [_run(scenario_type, repetition) for repetition in range(3)]
    runs[1].benchmark.detection_succeeded = False
    runs[1].benchmark.time_to_incident_ms = None
    runs[1].benchmark.diagnosis_rating = DiagnosisRating.INCORRECT
    runs[1].benchmark.recovery_succeeded = False
    runs[1].benchmark.benchmark_status = BenchmarkStatus.FAILED
    runs[2].benchmark = None

    result = summarize_repeatability(runs)["scenarios"][0]

    assert result["detection_success_rate"] == 33.33
    assert result["incident_creation_success_rate"] == 33.33
    assert result["rca_correctness_rate"] == 33.33
    assert result["recovery_success_rate"] == 33.33
    assert result["failed_or_incomplete_runs"] == [
        runs[1].id,
        runs[2].id,
    ]
