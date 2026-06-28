import os
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.events.constants import (
    KUBERNETES_DEPLOYMENT_HEALTHY,
    KUBERNETES_DEPLOYMENT_UNHEALTHY,
    KUBERNETES_POD_UNHEALTHY,
    KUBERNETES_RESTART_DETECTED,
)
from app.events.service import record_platform_event


try:
    from kubernetes import client, config
except ImportError:
    client = None
    config = None


DEFAULT_NAMESPACE = os.getenv("KUBERNETES_NAMESPACE", "platformiq-demo")
DEFAULT_ENVIRONMENT = os.getenv("PLATFORMIQ_ENVIRONMENT", "staging")


# Sprint 4H simple previous-state cache.
# This is enough for local demo / worker process.
# Later, move this to a kubernetes_workloads table.
_PREVIOUS_DEPLOYMENT_AVAILABLE_REPLICAS: Dict[str, int] = {}
_PREVIOUS_POD_RESTART_COUNTS: Dict[str, int] = {}


def emit_kubernetes_workload_events(
    db,
    *,
    service_id: str | None,
    environment: str,
    correlation_id: str,
    namespace: str,
    deployment_name: str,
    desired_replicas: int | None = None,
    available_replicas: int | None = None,
    previous_available_replicas: int | None = None,
    pod_name: str | None = None,
    pod_phase: str | None = None,
    pod_ready: bool | None = None,
    restart_count: int | None = None,
    previous_restart_count: int | None = None,
):
    """
    Emits only meaningful Kubernetes workload events.

    Sprint 4 rule:
    - Do not emit every tiny pod update.
    - Emit health changes, unhealthy pods, and restart increases.
    """

    emitted_count = 0

    has_deployment_replica_data = (
        desired_replicas is not None and available_replicas is not None
    )

    if has_deployment_replica_data:
        is_deployment_healthy = (
            desired_replicas > 0 and available_replicas >= desired_replicas
        )

        was_deployment_healthy = (
            previous_available_replicas is not None
            and desired_replicas > 0
            and previous_available_replicas >= desired_replicas
        )

        if is_deployment_healthy and not was_deployment_healthy:
            record_platform_event(
                db,
                event_type=KUBERNETES_DEPLOYMENT_HEALTHY,
                correlation_id=correlation_id,
                service_id=service_id,
                environment=environment,
                payload={
                    "namespace": namespace,
                    "deployment_name": deployment_name,
                    "desired_replicas": desired_replicas,
                    "available_replicas": available_replicas,
                    "previous_available_replicas": previous_available_replicas,
                },
            )
            emitted_count += 1

        if not is_deployment_healthy:
            record_platform_event(
                db,
                event_type=KUBERNETES_DEPLOYMENT_UNHEALTHY,
                correlation_id=correlation_id,
                service_id=service_id,
                environment=environment,
                payload={
                    "namespace": namespace,
                    "deployment_name": deployment_name,
                    "desired_replicas": desired_replicas,
                    "available_replicas": available_replicas,
                    "previous_available_replicas": previous_available_replicas,
                },
            )
            emitted_count += 1

    pod_is_unhealthy = pod_name and (
        pod_phase not in ("Running", "Succeeded") or pod_ready is False
    )

    if pod_is_unhealthy:
        record_platform_event(
            db,
            event_type=KUBERNETES_POD_UNHEALTHY,
            correlation_id=correlation_id,
            service_id=service_id,
            environment=environment,
            payload={
                "namespace": namespace,
                "deployment_name": deployment_name,
                "pod_name": pod_name,
                "pod_phase": pod_phase,
                "pod_ready": pod_ready,
            },
        )
        emitted_count += 1

    restart_increased = (
        pod_name
        and restart_count is not None
        and previous_restart_count is not None
        and restart_count > previous_restart_count
    )

    if restart_increased:
        record_platform_event(
            db,
            event_type=KUBERNETES_RESTART_DETECTED,
            correlation_id=correlation_id,
            service_id=service_id,
            environment=environment,
            payload={
                "namespace": namespace,
                "deployment_name": deployment_name,
                "pod_name": pod_name,
                "restart_count": restart_count,
                "previous_restart_count": previous_restart_count,
            },
        )
        emitted_count += 1

    return emitted_count


def _load_kubernetes_config() -> None:
    """
    Load Kubernetes config.

    Works in two places:
    - inside cluster using service account
    - local dev machine using kubeconfig
    """

    if client is None or config is None:
        raise RuntimeError(
            "kubernetes package is not installed. Install it with: pip install kubernetes"
        )

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()


def _deployment_key(namespace: str, deployment_name: str) -> str:
    return f"{namespace}/{deployment_name}"


def _pod_key(namespace: str, pod_name: str) -> str:
    return f"{namespace}/{pod_name}"


def _safe_int(value, default: int = 0) -> int:
    if value is None:
        return default

    try:
        return int(value)
    except Exception:
        return default


def _is_pod_ready(pod) -> bool:
    conditions = getattr(pod.status, "conditions", None) or []

    for condition in conditions:
        if condition.type == "Ready":
            return condition.status == "True"

    return False


def _get_pod_restart_count(pod) -> int:
    restart_count = 0

    container_statuses = getattr(pod.status, "container_statuses", None) or []

    for container_status in container_statuses:
        restart_count += _safe_int(getattr(container_status, "restart_count", 0))

    return restart_count


def _infer_deployment_name_from_pod(pod) -> str:
    labels = getattr(pod.metadata, "labels", None) or {}

    for label_key in [
        "app.kubernetes.io/name",
        "app",
        "service",
        "component",
    ]:
        if labels.get(label_key):
            return labels[label_key]

    owner_references = getattr(pod.metadata, "owner_references", None) or []

    for owner in owner_references:
        owner_name = getattr(owner, "name", None)

        if not owner_name:
            continue

        # Pods are often owned by ReplicaSets named like:
        # payment-service-7f9c8d6c6d
        # This strips the final hash-ish suffix for a cleaner deployment name.
        if "-" in owner_name:
            return "-".join(owner_name.split("-")[:-1]) or owner_name

        return owner_name

    return getattr(pod.metadata, "name", "unknown-pod")


def capture_kubernetes_workloads(
    db: Optional[Session] = None,
    *,
    namespace: str = DEFAULT_NAMESPACE,
    service_id: str | None = None,
    environment: str = DEFAULT_ENVIRONMENT,
    correlation_id: str | None = None,
) -> int:
    """
    Captures Kubernetes workload state and emits meaningful events.

    This function is intentionally simple for Sprint 4H:
    - deployment health events are based on desired vs available replicas
    - pod unhealthy events are based on phase/readiness
    - restart events are based on restart count increase
    """

    owns_db_session = db is None

    if db is None:
        db = SessionLocal()

    emitted_count = 0

    try:
        _load_kubernetes_config()

        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()

        deployments = apps_v1.list_namespaced_deployment(namespace=namespace).items
        pods = core_v1.list_namespaced_pod(namespace=namespace).items

        for deployment in deployments:
            deployment_name = deployment.metadata.name

            desired_replicas = _safe_int(
                getattr(deployment.spec, "replicas", None),
                default=0,
            )

            available_replicas = _safe_int(
                getattr(deployment.status, "available_replicas", None),
                default=0,
            )

            key = _deployment_key(namespace, deployment_name)

            previous_available_replicas = _PREVIOUS_DEPLOYMENT_AVAILABLE_REPLICAS.get(
                key
            )

            event_correlation_id = str(
                correlation_id or service_id or deployment_name
            )

            emitted_count += emit_kubernetes_workload_events(
                db,
                service_id=str(service_id) if service_id else None,
                environment=environment or "staging",
                correlation_id=event_correlation_id,
                namespace=namespace,
                deployment_name=deployment_name,
                desired_replicas=desired_replicas,
                available_replicas=available_replicas,
                previous_available_replicas=previous_available_replicas,
            )

            _PREVIOUS_DEPLOYMENT_AVAILABLE_REPLICAS[key] = available_replicas

        for pod in pods:
            pod_name = pod.metadata.name
            pod_phase = getattr(pod.status, "phase", None)
            pod_ready = _is_pod_ready(pod)
            restart_count = _get_pod_restart_count(pod)

            deployment_name = _infer_deployment_name_from_pod(pod)

            key = _pod_key(namespace, pod_name)
            previous_restart_count = _PREVIOUS_POD_RESTART_COUNTS.get(key)

            event_correlation_id = str(
                correlation_id or service_id or deployment_name or pod_name
            )

            emitted_count += emit_kubernetes_workload_events(
                db,
                service_id=str(service_id) if service_id else None,
                environment=environment or "staging",
                correlation_id=event_correlation_id,
                namespace=namespace,
                deployment_name=deployment_name,
                pod_name=pod_name,
                pod_phase=pod_phase,
                pod_ready=pod_ready,
                restart_count=restart_count,
                previous_restart_count=previous_restart_count,
            )

            _PREVIOUS_POD_RESTART_COUNTS[key] = restart_count

        if owns_db_session:
            db.commit()

        return emitted_count

    except Exception:
        if owns_db_session:
            db.rollback()
        raise

    finally:
        if owns_db_session:
            db.close()


def run_kubernetes_capture_once() -> int:
    """
    Convenience function for manual testing or Celery usage.
    """

    return capture_kubernetes_workloads()


# Backward-compatible aliases in case another file imports these names.
def capture_kubernetes_workload_state(*args, **kwargs) -> int:
    return capture_kubernetes_workloads(*args, **kwargs)


def capture_kubernetes_state(*args, **kwargs) -> int:
    return capture_kubernetes_workloads(*args, **kwargs)