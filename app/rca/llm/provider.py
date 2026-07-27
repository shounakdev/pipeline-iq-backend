from typing import Protocol

from app.rca.schemas import IncidentEvidenceBundle
from app.rca.llm.schemas import RCAReportDraft


class RCAProvider(Protocol):
    def generate_report(
        self,
        *,
        evidence: IncidentEvidenceBundle,
    ) -> RCAReportDraft:
        ...