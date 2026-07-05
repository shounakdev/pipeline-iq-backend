from sqlalchemy.orm import Session

from app.models import ServiceHealthSnapshot, ServiceHealthStatus
from app.observability.health_rules import classify_health


def create_health_snapshot(
    db: Session,
    service_id,
    service_name: str,
    environment: str,
    latency_ms: float | None,
    error_rate: float | None,
    cpu_usage: float | None,
    memory_usage: float | None,
    pod_restart_count: int | None,
    replica_count: int | None,
    available_replicas: int | None,
    source: str = "manual",
):
    status = classify_health(
        latency_ms=latency_ms,
        error_rate=error_rate,
        pod_restart_count=pod_restart_count,
        available_replicas=available_replicas,
        replica_count=replica_count,
    )

    snapshot = ServiceHealthSnapshot(
        service_id=str(service_id),
        service_name=service_name,
        environment=environment,
        status=ServiceHealthStatus(status),
        latency_ms=latency_ms,
        error_rate=error_rate,
        cpu_usage=cpu_usage,
        memory_usage=memory_usage,
        pod_restart_count=pod_restart_count,
        replica_count=replica_count,
        available_replicas=available_replicas,
        source=source,
    )

    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    return snapshot
