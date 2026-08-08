"""Inject latency between payment-service and a service dependency."""

from dataclasses import dataclass
from typing import Any

from app.chaos.scenarios.base import BaseChaosScenario
from app.models import ChaosScenarioType


@dataclass(frozen=True)
class NetworkDelayScenario(BaseChaosScenario):
    dependency_service: str = "order-service"
    latency_ms: int = 2000
    jitter_ms: int = 200

    scenario_type = ChaosScenarioType.NETWORK_DELAY
    failure_type = "NETWORK_DELAY"
    expected_diagnosis = "NETWORK_LATENCY"
    expected_remediation = None
    default_duration_seconds = 120

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.dependency_service:
            raise ValueError("dependency_service must not be empty")
        if self.latency_ms <= 0 or self.jitter_ms < 0:
            raise ValueError("latency must be positive and jitter non-negative")

    def failure_config(self) -> dict[str, Any]:
        return {
            **super().failure_config(),
            "dependency_service": self.dependency_service,
            "latency_ms": self.latency_ms,
            "jitter_ms": self.jitter_ms,
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
            "kind": "NetworkChaos",
            "metadata": self.metadata(
                run_id=run_id,
                operator_id=operator_id,
                deadline=deadline,
            ),
            "spec": {
                "action": "delay",
                "mode": "all",
                "duration": self.duration,
                "selector": self.selector(),
                "direction": "to",
                "target": {
                    "mode": "all",
                    "selector": self.selector(self.dependency_service),
                },
                "delay": {
                    "latency": f"{self.latency_ms}ms",
                    "jitter": f"{self.jitter_ms}ms",
                    "correlation": "0",
                },
            },
        }
