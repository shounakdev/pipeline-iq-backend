import json
from typing import Any

from app.rca.schemas import IncidentEvidenceBundle
from app.rca.llm.provider import RCAProvider
from app.rca.llm.schemas import RCAReportDraft
from app.rca.llm.validator import validate_rca_report


class RCAGatewayError(Exception):
    pass


class GuardedRCAGateway:
    def __init__(self, provider: RCAProvider):
        self.provider = provider

    def generate_validated_report(
        self,
        *,
        evidence: IncidentEvidenceBundle,
    ) -> dict[str, Any]:
        try:
            report: RCAReportDraft = self.provider.generate_report(evidence=evidence)
        except Exception as exc:
            raise RCAGatewayError("RCA provider failed to generate a valid report.") from exc

        evidence_json = json.loads(
            evidence.model_dump_json()
            if hasattr(evidence, "model_dump_json")
            else evidence.json()
        )

        return validate_rca_report(
            report=report,
            evidence_json=evidence_json,
        )


from app.rca.llm.local_provider import LocalRuleBasedRCAProvider


def generate_rca_from_evidence(
    evidence_bundle: dict,
    prompt_version: str = "rca_v1",
    model: str = "gpt-4.1-mini",
) -> dict[str, Any]:
    evidence = IncidentEvidenceBundle(**evidence_bundle)

    gateway = GuardedRCAGateway(
        provider=LocalRuleBasedRCAProvider()
    )

    return gateway.generate_validated_report(evidence=evidence)