from __future__ import annotations

from typing import Protocol

from app.rca.contracts import RCAEvidenceBundle, RCAReportContent


class RCAProvider(Protocol):
    def generate_report(
        self,
        evidence: RCAEvidenceBundle,
    ) -> RCAReportContent:
        ...


class RCAProviderError(RuntimeError):
    """Raised when the configured RCA provider cannot produce a report."""
