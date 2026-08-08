"""Inject a database-specific network delay for payment-service."""

from dataclasses import dataclass
from typing import Any

from app.chaos.scenarios.base import BaseChaosScenario
from app.models import ChaosScenarioType


@dataclass(frozen=True)
class DatabaseDelayScenario(BaseChaosScenario):
    database_service: str = "postgres"
    database_port: int = 5432
    latency_ms: int = 2000
    jitter_ms: int = 200

    scenario_type = ChaosScenarioType.DATABASE_DELAY
    failure_type = "DATABASE_DELAY"
    expected_diagnosis = "DATABASE_CONNECTIVITY"
    expected_remediation = None
    default_duration_seconds = 120

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.database_service:
            raise ValueError("database_service must not be empty")
        if not 1 <= self.database_port <= 65535:
            raise ValueError("database_port must be between 1 and 65535")
        if self.latency_ms <= 0 or self.jitter_ms < 0:
            raise ValueError("latency must be positive and jitter non-negative")

    def failure_config(self) -> dict[str, Any]:
        return {
            **super().failure_config(),
            "dependency_type": "database",
            "database_service": self.database_service,
            "database_port": self.database_port,
            "latency_ms": self.latency_ms,
            "jitter_ms": self.jitter_ms,
            "evidence_signatures": [
                "database timeout",
                "connection timed out",
                "postgresql",
            ],
        }

    def build_manifest(
        self,
        *,
        run_id: str,
        operator_id: str = "platformiq",
        deadline: str | None = None,
    ) -> dict[str, Any]:
        metadata = self.metadata(
            run_id=run_id,
            operator_id=operator_id,
            deadline=deadline,
        )
        metadata["annotations"].update(
            {
                "platformiq.io/dependency-type": "database",
                "platformiq.io/database-service": self.database_service,
                "platformiq.io/database-port": str(self.database_port),
                "platformiq.io/evidence-signature": "database-timeout",
            }
        )
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "NetworkChaos",
            "metadata": metadata,
            "spec": {
                "action": "delay",
                "mode": "all",
                "duration": self.duration,
                "selector": self.selector(),
                "direction": "to",
                "target": {
                    "mode": "all",
                    "selector": self.selector(self.database_service),
                },
                "delay": {
                    "latency": f"{self.latency_ms}ms",
                    "jitter": f"{self.jitter_ms}ms",
                    "correlation": "0",
                },
            },
        }
