from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import RCAFeedbackRating


class RCAGenerateRequest(BaseModel):
    force_regenerate: bool = False


class RCAGenerateResponse(BaseModel):
    incident_id: UUID
    evidence_id: UUID
    rca_report_id: UUID
    status: str
    message: str = "RCA generation has been queued."


class RCAEvidenceResponse(BaseModel):
    incident_id: UUID
    evidence_id: UUID
    status: str
    version: int
    source_statuses: dict[str, Any] = Field(default_factory=dict)
    completeness_score: float | None = None
    missing_sources: list[Any] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    collector_errors: list[Any] | None = None
    collection_started_at: datetime | None = None
    collected_at: datetime | None = None
    created_at: datetime


class RCAReportBody(BaseModel):
    probable_root_cause: str | None = None
    confidence: str | None = None
    supporting_evidence: list[Any] = Field(default_factory=list)
    recommended_actions: list[Any] = Field(default_factory=list)
    alternative_hypotheses: list[Any] = Field(default_factory=list)
    missing_evidence: list[Any] = Field(default_factory=list)
    confidence_explanation: str | None = None
    root_cause_category: str | None = None
    failure_reason: str | None = None


class RCAStatusResponse(BaseModel):
    status: str
    report: RCAReportBody | None = None


class RCAFeedbackRequest(BaseModel):
    rca_report_id: UUID
    rating: RCAFeedbackRating
    comment: str | None = Field(default=None, max_length=10_000)


class RCAFeedbackResponse(BaseModel):
    id: UUID
    incident_id: UUID
    rca_report_id: UUID
    rating: str
    comment: str | None = None
    submitted_by: str | None = None
    created_at: datetime