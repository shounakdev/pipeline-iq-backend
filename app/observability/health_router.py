from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.events.kafka_producer import get_kafka_producer
from app.observability.alert_service import emit_alerts_for_snapshot
from app.observability.collector import create_health_snapshot
from app.observability.schemas import (
    HealthSummaryItem,
    ServiceHealthSnapshotResponse,
)
from app.observability.service import (
    get_health_summary,
    get_latest_service_health,
    get_service_health_history,
)


router = APIRouter(prefix="/api/observability", tags=["Observability"])


class ManualHealthSnapshotRequest(BaseModel):
    service_id: UUID
    service_name: str
    environment: str = "staging"
    latency_ms: float | None = None
    error_rate: float | None = None
    cpu_usage: float | None = None
    memory_usage: float | None = None
    pod_restart_count: int | None = None
    replica_count: int | None = None
    available_replicas: int | None = None


@router.post("/health-snapshots/manual")
def create_manual_snapshot(
    request: ManualHealthSnapshotRequest,
    db: Session = Depends(get_db),
):
    snapshot = create_health_snapshot(
        db=db,
        service_id=str(request.service_id),
        service_name=request.service_name,
        environment=request.environment,
        latency_ms=request.latency_ms,
        error_rate=request.error_rate,
        cpu_usage=request.cpu_usage,
        memory_usage=request.memory_usage,
        pod_restart_count=request.pod_restart_count,
        replica_count=request.replica_count,
        available_replicas=request.available_replicas,
        source="manual",
    )

    kafka_producer = get_kafka_producer()

    emitted_events = emit_alerts_for_snapshot(
        snapshot=snapshot,
        kafka_producer=kafka_producer,
        correlation_id=str(snapshot.id),
        db=db,
    )

    return {
        "snapshot_id": str(snapshot.id),
        "service_id": str(snapshot.service_id),
        "service_name": snapshot.service_name,
        "environment": snapshot.environment,
        "status": snapshot.status.value
        if hasattr(snapshot.status, "value")
        else snapshot.status,
        "alerts_emitted": len(emitted_events),
        "alerts": emitted_events,
    }


@router.get(
    "/services/{service_id}/health",
    response_model=ServiceHealthSnapshotResponse,
)
def service_health(service_id: str, db: Session = Depends(get_db)):
    snapshot = get_latest_service_health(db, service_id)

    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail="No health snapshot found for service",
        )

    return snapshot


@router.get(
    "/services/{service_id}/health/history",
    response_model=list[ServiceHealthSnapshotResponse],
)
def service_health_history(
    service_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return get_service_health_history(db, service_id, limit=limit)


@router.get(
    "/health-summary",
    response_model=list[HealthSummaryItem],
)
def health_summary(db: Session = Depends(get_db)):
    return get_health_summary(db)