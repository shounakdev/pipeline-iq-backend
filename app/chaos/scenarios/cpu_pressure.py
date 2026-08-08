"""Saturate CPU on one payment-service pod."""

from dataclasses import dataclass
from typing import Any

from app.chaos.scenarios.base import BaseChaosScenario
from app.models import ChaosScenarioType


@dataclass(frozen=True)
class CpuPressureScenario(BaseChaosScenario):
    workers: int = 2
    load_percent: int = 90

    scenario_type = ChaosScenarioType.CPU_PRESSURE
    failure_type = "CPU_PRESSURE"
    expected_diagnosis = "RESOURCE_SATURATION"
    expected_remediation = "SCALE_REPLICAS"
    default_duration_seconds = 180

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.workers <= 0:
            raise ValueError("workers must be greater than zero")
        if not 1 <= self.load_percent <= 100:
            raise ValueError("load_percent must be between 1 and 100")

    def failure_config(self) -> dict[str, Any]:
        return {
            **super().failure_config(),
            "workers": self.workers,
            "load_percent": self.load_percent,
        }

    def build_manifest(
        self,
        *,
        run_id: str,
        operator_id: str = "platformiq",
        deadline: str | None = None,
    ) -> dict[str, Any]:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "StressChaos",
            "metadata": self.metadata(
                run_id=run_id,
                operator_id=operator_id,
                deadline=deadline,
            ),
            "spec": {
                "mode": "one",
                "duration": self.duration,
                "selector": self.selector(),
                "stressors": {
                    "cpu": {
                        "workers": self.workers,
                        "load": self.load_percent,
                    }
                },
            },
        }


CPUPressureScenario = CpuPressureScenario
