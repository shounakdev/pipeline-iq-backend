from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.rca.schemas import IncidentEvidenceBundle
from app.rca.llm.gateway import GuardedRCAGateway
from app.rca.llm.provider import RCAProvider


def collect_incident_evidence(
    db: Session,
    incident_id: UUID,
) -> IncidentEvidenceBundle:
    raise NotImplementedError(
        "Sprint 8A defines the RCA contract only. "
        "Evidence collection is implemented in a later checkpoint."
    )


def generate_rca_report(
    provider: RCAProvider,
    evidence: IncidentEvidenceBundle,
) -> dict[str, Any]:
    gateway = GuardedRCAGateway(provider)

    return gateway.generate_validated_report(evidence=evidence)