from typing import Literal

from pydantic import BaseModel, Field


RootCauseCategory = Literal[
    "DEPLOYMENT_CHANGE",
    "PIPELINE_QUALITY",
    "SLO_BREACH",
    "APPLICATION_ERROR",
    "DEPENDENCY_FAILURE",
    "INFRASTRUCTURE",
    "KUBERNETES",
    "INSUFFICIENT_EVIDENCE",
    "UNKNOWN",
]

RCAConfidence = Literal["LOW", "MEDIUM", "HIGH"]


class EvidenceObservation(BaseModel):
    summary: str
    evidence_path: str


class AlternativeHypothesis(BaseModel):
    hypothesis: str
    confidence: RCAConfidence
    supporting_evidence_paths: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class RecommendedAction(BaseModel):
    action: str
    evidence_path: str | None = None
    advisory_only: bool = True


class RCAReportDraft(BaseModel):
    probable_root_cause: str
    root_cause_category: RootCauseCategory
    confidence: RCAConfidence

    supporting_observations: list[EvidenceObservation] = Field(default_factory=list)
    contradicting_observations: list[EvidenceObservation] = Field(default_factory=list)
    alternative_hypotheses: list[AlternativeHypothesis] = Field(default_factory=list)

    missing_evidence: list[str] = Field(default_factory=list)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)

    model: str
    prompt_version: str