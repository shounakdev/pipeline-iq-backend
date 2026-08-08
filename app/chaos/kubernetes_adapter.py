"""Narrow Chaos Mesh Kubernetes client adapter."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from app.chaos.exceptions import ChaosKubernetesError


@dataclass(frozen=True)
class CreatedChaosResource:
    kind: str
    name: str
    uid: str | None


def build_podchaos_manifest(
    *,
    run_id: str,
    environment: str,
    namespace: str,
    service_name: str,
    operator_id: str,
    deadline: str,
    duration_seconds: int,
) -> dict[str, Any]:
    resource_name = f"platformiq-{run_id}".lower()
    return {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": resource_name,
            "namespace": namespace,
            "labels": {
                "platformiq.io/environment": environment,
                "platformiq.io/service": service_name,
                "platformiq.io/managed-by": "platformiq",
            },
            "annotations": {
                "platformiq.io/operator": operator_id,
                "platformiq.io/run-id": run_id,
                "platformiq.io/deadline": deadline,
                "platformiq.io/cleanup-behavior": "delete",
            },
        },
        "spec": {
            "action": "pod-kill",
            "mode": "one",
            "duration": f"{duration_seconds}s",
            "selector": {
                "namespaces": [namespace],
                "labelSelectors": {
                    "app.kubernetes.io/name": service_name,
                },
            },
        },
    }


class ChaosMeshAdapter:
    group = "chaos-mesh.org"
    version = "v1alpha1"
    plural = "podchaos"

    def __init__(self, api: client.CustomObjectsApi | None = None):
        if api is None:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            api = client.CustomObjectsApi()
        self.api = api

    def create_podchaos(
        self,
        *,
        namespace: str,
        manifest: dict[str, Any],
    ) -> CreatedChaosResource:
        try:
            resource = self.api.create_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=namespace,
                plural=self.plural,
                body=manifest,
            )
        except ApiException as exc:
            raise ChaosKubernetesError(
                f"Chaos Mesh create failed with HTTP {exc.status}"
            ) from exc
        metadata = resource.get("metadata", {})
        return CreatedChaosResource(
            kind="PodChaos",
            name=metadata.get("name", manifest["metadata"]["name"]),
            uid=metadata.get("uid"),
        )

    def delete_podchaos_and_wait(
        self,
        *,
        namespace: str,
        name: str,
        timeout_seconds: int = 30,
    ) -> None:
        try:
            self.api.delete_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=namespace,
                plural=self.plural,
                name=name,
                body=client.V1DeleteOptions(
                    propagation_policy="Foreground"
                ),
            )
        except ApiException as exc:
            if exc.status != 404:
                raise ChaosKubernetesError(
                    f"Chaos Mesh delete failed with HTTP {exc.status}"
                ) from exc

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                self.api.get_namespaced_custom_object(
                    group=self.group,
                    version=self.version,
                    namespace=namespace,
                    plural=self.plural,
                    name=name,
                )
            except ApiException as exc:
                if exc.status == 404:
                    return
                raise ChaosKubernetesError(
                    f"Chaos Mesh read failed with HTTP {exc.status}"
                ) from exc
            time.sleep(0.5)
        raise ChaosKubernetesError(
            "Timed out waiting for Chaos Mesh resource deletion"
        )
