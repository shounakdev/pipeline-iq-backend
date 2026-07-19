from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IncidentEventOut(BaseModel):
    id: UUID
    incident_id: UUID
    event_type: str
    message: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


class IncidentOut(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    severity: str
    status: str
    service_id: str
    environment: str
    correlation_id: str
    triggered_by_event_id: str | None = None
    started_at: datetime
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IncidentDetailOut(IncidentOut):
    events: list[IncidentEventOut] = []


class TimelineItemOut(BaseModel):
    timestamp: datetime
    source: str
    event_type: str
    title: str
    details: dict[str, Any] = {}