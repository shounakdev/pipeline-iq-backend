"""Controlled known-bad release profile for payment-service."""

from dataclasses import dataclass
from typing import Any

from app.chaos.scenarios.base import BaseChaosScenario
from app.models import ChaosScenarioType


@dataclass(frozen=True)
class FaultyReleaseScenario(BaseChaosScenario):
    """Use an approved, reversible fault resource as the bad configuration."""

    port: int = 8080
    path: str = "/*"
    release_revision: str = "chaos-faulty-release"

    scenario_type = ChaosScenarioType.FAULTY_RELEASE
    failure_type = "FAULTY_RELEASE"
    expected_diagnosis = "APPLICATION_REGRESSION"
    expected_remediation = "ROLLBACK_DEPLOYMENT"
    default_duration_seconds = 120

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not self.release_revision:
            raise ValueError("release_revision must not be empty")

    def failure_config(self) -> dict[str, Any]:
        return {
            **super().failure_config(),
            "profile": "known_bad_http_configuration",
            "release_revision": self.release_revision,
            "port": self.port,
            "path": self.path,
            "abort_requests": True,
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
        metadata["labels"]["platformiq.io/release-revision"] = (
            self.release_revision
        )
        metadata["annotations"]["platformiq.io/fault-profile"] = (
            "known-bad-http-configuration"
        )
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "HTTPChaos",
            "metadata": metadata,
            "spec": {
                "mode": "all",
                "duration": self.duration,
                "selector": self.selector(),
                "target": "Request",
                "port": self.port,
                "method": "GET",
                "path": self.path,
                "abort": True,
            },
        }
