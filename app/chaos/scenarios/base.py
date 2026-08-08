"""Shared contract and manifest helpers for repeatable chaos scenarios."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, ClassVar

from app.chaos.adapters.base import BaseChaosAdapter, FaultInjectionResult
from app.models import ChaosScenarioType


_DNS_LABEL_RE = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True)
class BaseChaosScenario(ABC):
    """A reusable scenario definition that owns injection and cleanup metadata."""

    namespace: str
    service_name: str = "payment-service"
    environment: str = "staging"
    duration_seconds: int | None = None

    scenario_type: ClassVar[ChaosScenarioType]
    failure_type: ClassVar[str]
    expected_diagnosis: ClassVar[str]
    expected_remediation: ClassVar[str | None] = None
    default_duration_seconds: ClassVar[int]

    def __post_init__(self) -> None:
        duration = (
            self.default_duration_seconds
            if self.duration_seconds is None
            else self.duration_seconds
        )
        if not self.namespace:
            raise ValueError("namespace must not be empty")
        if not self.service_name:
            raise ValueError("service_name must not be empty")
        if duration <= 0:
            raise ValueError("duration_seconds must be greater than zero")
        object.__setattr__(self, "duration_seconds", duration)

    @property
    def duration(self) -> str:
        """Chaos Mesh duration value."""
        return f"{self.duration_seconds}s"

    def resource_name(self, run_id: str) -> str:
        clean_run_id = _DNS_LABEL_RE.sub("-", run_id.lower()).strip("-")
        clean_scenario = self.scenario_type.value.lower().replace("_", "-")
        name = f"platformiq-{clean_scenario}-{clean_run_id}".strip("-")
        return name[:63].rstrip("-")

    def selector(self, service_name: str | None = None) -> dict[str, Any]:
        return {
            "namespaces": [self.namespace],
            "labelSelectors": {
                # The demo-service Helm charts and raw manifests use ``app``.
                "app": service_name or self.service_name,
            },
        }

    def metadata(
        self,
        *,
        run_id: str,
        operator_id: str,
        deadline: str | None,
    ) -> dict[str, Any]:
        if deadline is None:
            deadline = (
                datetime.now(timezone.utc)
                + timedelta(seconds=int(self.duration_seconds))
            ).isoformat()
        return {
            "name": self.resource_name(run_id),
            "namespace": self.namespace,
            "labels": {
                "platformiq.io/environment": self.environment,
                "platformiq.io/service": self.service_name,
                "platformiq.io/scenario": self.scenario_type.value.lower(),
                "platformiq.io/managed-by": "platformiq",
            },
            "annotations": {
                "platformiq.io/operator": operator_id,
                "platformiq.io/run-id": run_id,
                "platformiq.io/deadline": deadline,
                "platformiq.io/duration-seconds": str(self.duration_seconds),
                "platformiq.io/cleanup-behavior": "delete",
                "platformiq.io/expected-diagnosis": self.expected_diagnosis,
                "platformiq.io/expected-remediation": (
                    self.expected_remediation or "NONE"
                ),
            },
        }

    @abstractmethod
    def build_manifest(
        self,
        *,
        run_id: str,
        operator_id: str = "platformiq",
        deadline: str | None = None,
    ) -> dict[str, Any]:
        """Build the Kubernetes fault resource for one run."""

    def generate_manifest(
        self,
        *,
        run_id: str,
        operator_id: str = "platformiq",
        deadline: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility alias used by callers that generate templates."""
        return self.build_manifest(
            run_id=run_id,
            operator_id=operator_id,
            deadline=deadline,
        )

    def experiment_values(self) -> dict[str, Any]:
        """Values suitable for ``chaos.repository.create_experiment``."""
        return {
            "scenario_type": self.scenario_type,
            "target_environment": self.environment,
            "target_namespace": self.namespace,
            "failure_type": self.failure_type,
            "failure_config": self.failure_config(),
            "expected_behavior": {
                "diagnosis": self.expected_diagnosis,
                "remediation": self.expected_remediation,
                "recovery_expected": True,
            },
        }

    def failure_config(self) -> dict[str, Any]:
        return {"duration_seconds": self.duration_seconds}

    def inject(
        self,
        adapter: BaseChaosAdapter,
        *,
        run_id: str,
        operator_id: str = "platformiq",
        deadline: str | None = None,
    ) -> FaultInjectionResult:
        return adapter.inject_fault(
            namespace=self.namespace,
            manifest=self.build_manifest(
                run_id=run_id,
                operator_id=operator_id,
                deadline=deadline,
            ),
        )

    def cleanup(
        self,
        adapter: BaseChaosAdapter,
        resource: FaultInjectionResult,
        *,
        timeout_seconds: int = 30,
    ) -> bool:
        """Delete the injected resource and verify that it is gone."""
        adapter.remove_fault(
            resource_kind=resource["resource_kind"],
            resource_name=resource["resource_name"],
            namespace=resource["namespace"],
        )
        return adapter.verify_cleanup(
            resource_kind=resource["resource_kind"],
            resource_name=resource["resource_name"],
            namespace=resource["namespace"],
            timeout_seconds=timeout_seconds,
        )


# Concise alias for callers that prefer ``ChaosScenario``.
ChaosScenario = BaseChaosScenario
