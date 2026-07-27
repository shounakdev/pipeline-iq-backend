from app.rca.schemas import IncidentEvidenceBundle
from app.rca.llm.schemas import EvidenceObservation, RCAReportDraft, RecommendedAction


class LocalRuleBasedRCAProvider:
    def generate_report(
        self,
        *,
        evidence: IncidentEvidenceBundle,
    ) -> RCAReportDraft:
        data = evidence.model_dump() if hasattr(evidence, "model_dump") else dict(evidence)

        deployment = data.get("deployment") or {}
        metrics = data.get("metrics") or {}
        logs = data.get("logs") or {}
        traces = data.get("traces") or {}

        supporting = []

        if deployment.get("status") == "COLLECTED":
            supporting.append(
                EvidenceObservation(
                    summary="A deployment was available in the incident evidence window.",
                    evidence_path="deployment.status",
                )
            )

        if metrics.get("status") == "COLLECTED":
            supporting.append(
                EvidenceObservation(
                    summary="Metrics evidence was available for the incident window.",
                    evidence_path="metrics.status",
                )
            )

        if logs.get("status") == "COLLECTED":
            supporting.append(
                EvidenceObservation(
                    summary="Log evidence was available for the incident window.",
                    evidence_path="logs.status",
                )
            )

        if traces.get("status") == "COLLECTED":
            supporting.append(
                EvidenceObservation(
                    summary="Trace evidence was available for the incident window.",
                    evidence_path="traces.status",
                )
            )

        if not supporting:
            return RCAReportDraft(
                probable_root_cause="Insufficient evidence to determine a reliable root cause.",
                root_cause_category="INSUFFICIENT_EVIDENCE",
                confidence="LOW",
                supporting_observations=[],
                contradicting_observations=[],
                alternative_hypotheses=[],
                missing_evidence=[
                    "Deployment correlation, metrics, logs, and traces are unavailable."
                ],
                recommended_actions=[
                    RecommendedAction(
                        action="Collect logs, metrics, traces, and deployment correlation before selecting a remediation.",
                        advisory_only=True,
                    )
                ],
                model="local-rule-based",
                prompt_version="rca-prompt-v1",
            )

        confidence = "LOW"
        if len(supporting) >= 2:
            confidence = "MEDIUM"

        return RCAReportDraft(
            probable_root_cause="Available evidence indicates a possible incident correlation, but RCA confidence remains limited until stronger telemetry is available.",
            root_cause_category="UNKNOWN",
            confidence=confidence,
            supporting_observations=supporting,
            contradicting_observations=[],
            alternative_hypotheses=[],
            missing_evidence=[],
            recommended_actions=[
                RecommendedAction(
                    action="Review the collected evidence and gather any missing telemetry before remediation.",
                    advisory_only=True,
                )
            ],
            model="local-rule-based",
            prompt_version="rca-prompt-v1",
        )