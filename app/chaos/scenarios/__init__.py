"""Reusable, duration-bounded chaos scenario templates."""

from app.chaos.scenarios.base import BaseChaosScenario, ChaosScenario
from app.chaos.scenarios.cpu_pressure import (
    CPUPressureScenario,
    CpuPressureScenario,
)
from app.chaos.scenarios.database_delay import DatabaseDelayScenario
from app.chaos.scenarios.faulty_release import FaultyReleaseScenario
from app.chaos.scenarios.network_delay import NetworkDelayScenario
from app.chaos.scenarios.pod_kill import PodKillScenario

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
]
