from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.rca.contracts import RCAEvidenceBundle


class RCAEvidenceCollector(Protocol):
    def collect(
        self,
        db: Session,
        incident_id: UUID,
    ) -> RCAEvidenceBundle:
        ...


class EvidenceCollectionError(RuntimeError):
    """Raised when minimum RCA evidence cannot be collected."""
