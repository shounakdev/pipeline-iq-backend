"""Reusable, duration-bounded chaos scenario templates."""

from typing import Any

from app.chaos.scenarios.base import BaseChaosScenario, ChaosScenario
from app.chaos.scenarios.cpu_pressure import (
    CPUPressureScenario,
    CpuPressureScenario,
)
from app.chaos.scenarios.database_delay import DatabaseDelayScenario
from app.chaos.scenarios.faulty_release import FaultyReleaseScenario
from app.chaos.scenarios.network_delay import NetworkDelayScenario
from app.chaos.scenarios.pod_kill import PodKillScenario
from app.models import ChaosScenarioType

SCENARIO_TYPES = {
    scenario.scenario_type: scenario
    for scenario in (
        FaultyReleaseScenario,
        PodKillScenario,
        NetworkDelayScenario,
        DatabaseDelayScenario,
        CpuPressureScenario,
    )
}


def scenario_from_experiment(
    experiment: Any,
    *,
    duration_seconds: int | None = None,
) -> BaseChaosScenario:
    """Materialize the configured scenario without trusting arbitrary kwargs.

    Persisted ``failure_config`` contains both constructor inputs and descriptive
    evidence fields.  Copy only the inputs owned by each scenario so older
    experiment rows remain executable as the schema evolves.
    """
    scenario_type = getattr(
        experiment.scenario_type,
        "value",
        experiment.scenario_type,
    )
    try:
        enum_type = next(
            item for item in SCENARIO_TYPES if item.value == str(scenario_type)
        )
    except StopIteration as exc:
        raise ValueError(f"Unsupported chaos scenario: {scenario_type}") from exc

    scenario_class = SCENARIO_TYPES[enum_type]
    config = (
        experiment.failure_config
        if isinstance(experiment.failure_config, dict)
        else {}
    )
    allowed_fields = {
        ChaosScenarioType.FAULTY_RELEASE: ("port", "path", "release_revision"),
        ChaosScenarioType.POD_KILL: (),
        ChaosScenarioType.NETWORK_DELAY: (
            "dependency_service",
            "latency_ms",
            "jitter_ms",
        ),
        ChaosScenarioType.DATABASE_DELAY: (
            "database_service",
            "database_port",
            "latency_ms",
            "jitter_ms",
        ),
        ChaosScenarioType.CPU_PRESSURE: ("workers", "load_percent"),
    }
    kwargs = {
        name: config[name]
        for name in allowed_fields[enum_type]
        if name in config
    }
    configured_duration = (
        duration_seconds
        if duration_seconds is not None
        else config.get("duration_seconds")
    )
    return scenario_class(
        namespace=experiment.target_namespace,
        service_name=experiment.target_service.name,
        environment=experiment.target_environment,
        duration_seconds=configured_duration,
        **kwargs,
    )

__all__ = [
    "BaseChaosScenario",
    "ChaosScenario",
    "CPUPressureScenario",
    "CpuPressureScenario",
    "DatabaseDelayScenario",
    "FaultyReleaseScenario",
    "NetworkDelayScenario",
    "PodKillScenario",
    "SCENARIO_TYPES",
    "scenario_from_experiment",
]
