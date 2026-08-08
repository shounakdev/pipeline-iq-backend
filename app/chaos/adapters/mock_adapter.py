"""Deterministic in-memory adapter for tests without Kubernetes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.chaos.adapters.base import (
    BaseChaosAdapter,
    FaultInjectionResult,
    FaultStatusResult,
)


class MockChaosAdapter(BaseChaosAdapter):
    DEFAULT_INJECTED_AT = "2026-08-02T10:00:00Z"

    def __init__(self, *, injected_at: str = DEFAULT_INJECTED_AT):
        self.injected_at = injected_at
        self.resources: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.injected_manifests: list[dict[str, Any]] = []

    def inject_fault(
        self,
        *,
        namespace: str,
        manifest: dict[str, Any],
    ) -> FaultInjectionResult:
        resource_kind = str(manifest["kind"])
        resource_name = str(manifest["metadata"]["name"])
        key = (namespace, resource_kind, resource_name)
        self.resources[key] = deepcopy(manifest)
        self.injected_manifests.append(deepcopy(manifest))
        return {
            "resource_kind": resource_kind,
            "resource_name": resource_name,
            "namespace": namespace,
            "status": "INJECTED",
            "injected_at": self.injected_at,
        }

    def get_fault_status(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
    ) -> FaultStatusResult:
        key = (namespace, resource_kind, resource_name)
        return {
            "resource_kind": resource_kind,
            "resource_name": resource_name,
            "namespace": namespace,
            "status": "INJECTED" if key in self.resources else "NOT_FOUND",
        }

    def remove_fault(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
    ) -> None:
        self.resources.pop((namespace, resource_kind, resource_name), None)

    def verify_cleanup(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
        timeout_seconds: int = 30,
    ) -> bool:
        del timeout_seconds
        key = (namespace, resource_kind, resource_name)
        return key not in self.resources


MockAdapter = MockChaosAdapter