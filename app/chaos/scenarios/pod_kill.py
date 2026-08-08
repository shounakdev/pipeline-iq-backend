"""Kill one payment-service pod and let Kubernetes recreate it."""

from typing import Any

from app.chaos.scenarios.base import BaseChaosScenario
from app.models import ChaosScenarioType


class PodKillScenario(BaseChaosScenario):
    scenario_type = ChaosScenarioType.POD_KILL
    failure_type = "POD_KILL"
    expected_diagnosis = "POD_FAILURE"
    expected_remediation = "RESTART_POD"
    default_duration_seconds = 30

    def build_manifest(
        self,
        *,
        run_id: str,
        operator_id: str = "platformiq",
        deadline: str | None = None,
    ) -> dict[str, Any]:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "PodChaos",
            "metadata": self.metadata(
                run_id=run_id,
                operator_id=operator_id,
                deadline=deadline,
            ),
            "spec": {
                "action": "pod-kill",
                "mode": "one",
                "duration": self.duration,
                "selector": self.selector(),
            },
        }
