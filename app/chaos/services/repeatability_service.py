"""Aggregate repeatability evidence across chaos experiment runs."""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean, pvariance
from typing import Any, Iterable

from app.models import BenchmarkStatus, DiagnosisRating


def _value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _rate(successes: int, total: int) -> float:
    return round((successes / total) * 100, 2) if total else 0.0


def _timing(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"average_ms": None, "maximum_ms": None, "variance_ms2": None}
    return {
        "average_ms": round(fmean(values), 2),
        "maximum_ms": max(values),
        # Population variance describes the complete selected run set.
        "variance_ms2": round(pvariance(values), 2),
    }


def summarize_repeatability(runs: Iterable[Any]) -> dict[str, Any]:
    """Return stable scenario and overall metrics for persisted chaos runs."""
    grouped: dict[str, list[Any]] = defaultdict(list)
    for run in runs:
        grouped[_value(run.experiment.scenario_type)].append(run)

    scenarios: list[dict[str, Any]] = []
    all_runs: list[Any] = []
    for scenario_type in sorted(grouped):
        scenario_runs = grouped[scenario_type]
        all_runs.extend(scenario_runs)
        benchmarks = [run.benchmark for run in scenario_runs if run.benchmark]
        detection_times = [
            item.time_to_detect_ms
            for item in benchmarks
            if item.time_to_detect_ms is not None
        ]
        recovery_times = [
            item.time_to_recover_ms
            for item in benchmarks
            if item.time_to_recover_ms is not None
        ]
        failed = [
            str(run.id)
            for run in scenario_runs
            if run.benchmark is None
            or run.benchmark.benchmark_status
            in {BenchmarkStatus.FAILED, BenchmarkStatus.INCOMPLETE}
        ]
        scenarios.append(
            {
                "scenario_type": scenario_type,
                "executions": len(scenario_runs),
                "detection_success_rate": _rate(
                    sum(item.detection_succeeded is True for item in benchmarks),
                    len(scenario_runs),
                ),
                "incident_creation_success_rate": _rate(
                    sum(item.time_to_incident_ms is not None for item in benchmarks),
                    len(scenario_runs),
                ),
                "rca_correctness_rate": _rate(
                    sum(
                        item.diagnosis_rating == DiagnosisRating.CORRECT
                        for item in benchmarks
                    ),
                    len(scenario_runs),
                ),
                "recovery_success_rate": _rate(
                    sum(item.recovery_succeeded is True for item in benchmarks),
                    len(scenario_runs),
                ),
                "detection_time": _timing(detection_times),
                "recovery_time": _timing(recovery_times),
                "failed_or_incomplete_runs": failed,
            }
        )

    total = len(all_runs)
    return {
        "total_executions": total,
        "minimum_runs_per_scenario_met": bool(scenarios)
        and all(item["executions"] >= 3 for item in scenarios),
        "scenarios": scenarios,
    }


__all__ = ["summarize_repeatability"]
