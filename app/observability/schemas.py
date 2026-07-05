from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ServiceHealthSnapshotResponse(BaseModel):
    id: UUID
    service_id: str
    service_name: str
    environment: str
    status: str
    latency_ms: float | None = None
    error_rate: float | None = None
    cpu_usage: float | None = None
    memory_usage: float | None = None
    pod_restart_count: int | None = None
    replica_count: int | None = None
    available_replicas: int | None = None
    source: str
    created_at: datetime

    class Config:
        from_attributes = True


class HealthSummaryItem(BaseModel):
    service_id: str
    service_name: str
    environment: str
    status: str
    latency_ms: float | None = None
    error_rate: float | None = None
    pod_restart_count: int | None = None
    available_replicas: int | None = None
    replica_count: int | None = None

    class Config:
        from_attributes = True