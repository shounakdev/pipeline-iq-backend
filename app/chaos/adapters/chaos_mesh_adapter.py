"""Chaos Mesh implementation of the provider-neutral chaos adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from app.chaos.adapters.base import (
    BaseChaosAdapter,
    FaultInjectionResult,
    FaultStatusResult,
)
from app.chaos.exceptions import ChaosKubernetesError


class ChaosMeshAdapter(BaseChaosAdapter):
    group = "chaos-mesh.org"
    version = "v1alpha1"
    _plurals = {
        "PodChaos": "podchaos",
        "NetworkChaos": "networkchaos",
        "StressChaos": "stresschaos",
        "IOChaos": "iochaos",
        "TimeChaos": "timechaos",
        "DNSChaos": "dnschaos",
        "HTTPChaos": "httpchaos",
    }

    def __init__(self, api: client.CustomObjectsApi | None = None):
        if api is None:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            api = client.CustomObjectsApi()
        self.api = api

    @classmethod
    def _plural_for(cls, resource_kind: str) -> str:
        try:
            return cls._plurals[resource_kind]
        except KeyError as exc:
            raise ChaosKubernetesError(
                f"Unsupported Chaos Mesh resource kind: {resource_kind}"
            ) from exc

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def inject_fault(
        self,
        *,
        namespace: str,
        manifest: dict[str, Any],
    ) -> FaultInjectionResult:
        resource_kind = str(manifest.get("kind", ""))
        resource_name = str(manifest.get("metadata", {}).get("name", ""))
        if not resource_kind or not resource_name:
            raise ChaosKubernetesError(
                "Chaos Mesh manifest requires kind and metadata.name"
            )
        try:
            resource = self.api.create_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=namespace,
                plural=self._plural_for(resource_kind),
                body=manifest,
            )
        except ApiException as exc:
            raise ChaosKubernetesError(
                f"Chaos Mesh create failed with HTTP {exc.status}"
            ) from exc

        metadata = resource.get("metadata", {})
        return {
            "resource_kind": resource_kind,
            "resource_name": metadata.get("name", resource_name),
            "namespace": namespace,
            "status": "INJECTED",
            "injected_at": self._timestamp(),
            "resource_uid": metadata.get("uid"),
        }

    def get_fault_status(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
    ) -> FaultStatusResult:
        try:
            resource = self.api.get_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=namespace,
                plural=self._plural_for(resource_kind),
                name=resource_name,
            )
        except ApiException as exc:
            if exc.status == 404:
                status = "NOT_FOUND"
            else:
                raise ChaosKubernetesError(
                    f"Chaos Mesh read failed with HTTP {exc.status}"
                ) from exc
        else:
            provider_status = resource.get("status", {})
            status = "RUNNING" if provider_status else "INJECTED"
        return {
            "resource_kind": resource_kind,
            "resource_name": resource_name,
            "namespace": namespace,
            "status": status,
        }

    def remove_fault(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
    ) -> None:
        try:
            self.api.delete_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=namespace,
                plural=self._plural_for(resource_kind),
                name=resource_name,
                body=client.V1DeleteOptions(propagation_policy="Foreground"),
            )
        except ApiException as exc:
            if exc.status != 404:
                raise ChaosKubernetesError(
                    f"Chaos Mesh delete failed with HTTP {exc.status}"
                ) from exc

    def verify_cleanup(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
        timeout_seconds: int = 30,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = self.get_fault_status(
                resource_kind=resource_kind,
                resource_name=resource_name,
                namespace=namespace,
            )
            if status["status"] == "NOT_FOUND":
                return True
            time.sleep(0.5)
        return False