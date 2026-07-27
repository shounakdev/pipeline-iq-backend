from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from app.models import EvidenceCollectionStatus, Incident, IncidentEvidence, Service


class CollectorStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class EvidenceCollectionContext:
    incident_id: UUID
    incident_number: str | None
    service_id: UUID | str | None
    service_name: str | None
    environment: str | None
    failure_started_at: datetime | None
    detected_at: datetime
    current_time: datetime
    before_window_start: datetime
    before_window_end: datetime
    after_window_start: datetime
    after_window_end: datetime
    suspected_deployment_id: UUID | None = None
    related_alert_ids: list[UUID | str] = field(default_factory=list)


@dataclass
class CollectorResult:
    source_name: str
    status: CollectorStatus
    data: dict[str, Any] | list[Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int | None = None



class EvidenceCollector(Protocol):
    source_name: str

    def collect(self, context: EvidenceCollectionContext) -> CollectorResult:
        ...