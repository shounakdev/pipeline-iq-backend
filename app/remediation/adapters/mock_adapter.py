"""Deterministic remediation adapter used before live integrations."""

from __future__ import annotations

from typing import Any

from app.models import ActionType


class UnsupportedRemediationActionError(Exception):
    """Raised when an adapter cannot execute an action."""


class MockRemediationAdapter:
    """Return deterministic results without external side effects."""

    def execute(
        self,
        *,
        action_type: ActionType,
        command_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action_type == ActionType.ROLLBACK_DEPLOYMENT:
            return {
                "command_type": "ARGOCD_ROLLBACK",
                "status": "COMPLETED",
                "message": "Rollback command accepted.",
                "target_revision": command_payload[
                    "target_revision"
                ],
            }

        if action_type == ActionType.RESTART_POD:
            return {
                "command_type": "KUBERNETES_RESTART_POD",
                "status": "COMPLETED",
                "message": "Pod restart command accepted.",
                "target_pod": command_payload["target_pod"],
            }

        if action_type == ActionType.SCALE_REPLICAS:
            return {
                "command_type": "KUBERNETES_SCALE_REPLICAS",
                "status": "COMPLETED",
                "message": "Replica scale command accepted.",
                "replica_count": command_payload[
                    "replica_count"
                ],
            }

        if action_type == ActionType.REDEPLOY_REVISION:
            return {
                "command_type": "ARGOCD_REDEPLOY_REVISION",
                "status": "COMPLETED",
                "message": "Redeploy command accepted.",
                "target_revision": command_payload[
                    "target_revision"
                ],
            }

        raise UnsupportedRemediationActionError(
            f"Unsupported remediation action: {action_type}"
        )
