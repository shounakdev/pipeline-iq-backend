# app/schemas/rca/evidence.py

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class EvidenceSourceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NO_DATA = "NO_DATA"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class RCAConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RootCauseCategory(str, Enum):
    DATABASE_DEPENDENCY = "DATABASE_DEPENDENCY"
    APPLICATION_REGRESSION = "APPLICATION_REGRESSION"
    RELEASE_CONFIGURATION = "RELEASE_CONFIGURATION"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    NETWORK_DEPENDENCY = "NETWORK_DEPENDENCY"
    EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY"
    KUBERNETES_RUNTIME = "KUBERNETES_RUNTIME"
    CAPACITY_OR_SCALING = "CAPACITY_OR_SCALING"
    UNKNOWN = "UNKNOWN"


class RecommendationPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EvidenceSourceMetadata(BaseModel):
    source: str = Field(min_length=1)
    status: EvidenceSourceStatus
    queried_at: datetime
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    record_count: int = Field(ge=0)
    error: Optional[str] = None


class TimeWindowEvidence(BaseModel):
    anchor: datetime
    before_start: datetime
    before_end: datetime
    after_start: datetime
    after_end: datetime


class IncidentContextEvidence(BaseModel):
    incident_id: UUID
    incident_number: str
    status: str
    severity: str
    affected_service: Optional[str] = None
    environment: Optional[str] = None
    failure_started_at: Optional[datetime] = None
    detected_at: datetime


class DeploymentEvidence(BaseModel):
    metadata: EvidenceSourceMetadata
    deployment_id: Optional[str] = None
    version: Optional[str] = None
    commit_sha: Optional[str] = None
    status: Optional[str] = None
    deployed_at: Optional[datetime] = None
    deployed_minutes_before_alert: Optional[float] = None
    release_risk_score: Optional[float] = None


class PipelineEvidence(BaseModel):
    metadata: EvidenceSourceMetadata
    pipeline_run_id: Optional[str] = None
    status: Optional[str] = None
    failure_stage: Optional[str] = None
    quality_gate_result: Optional[str] = None
    test_result: Optional[str] = None
    security_findings: List[Dict[str, Any]] = Field(default_factory=list)
    trivy_findings: List[Dict[str, Any]] = Field(default_factory=list)
    sonarqube_findings: List[Dict[str, Any]] = Field(default_factory=list)


class SLOBreachEvidence(BaseModel):
    metadata: EvidenceSourceMetadata
    breached: bool = False
    slo_type: Optional[str] = None
    target: Optional[float] = None
    measured_value: Optional[float] = None
    burn_rate: Optional[float] = None
    error_budget_status: Optional[str] = None


class MetricsEvidence(BaseModel):
    metadata: EvidenceSourceMetadata
    latency_ms: Optional[float] = None
    error_rate: Optional[float] = None
    request_rate: Optional[float] = None
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    pod_restart_count: Optional[int] = None
    series: List[Dict[str, Any]] = Field(default_factory=list)


class LogsEvidence(BaseModel):
    metadata: EvidenceSourceMetadata
    error_patterns: List[Dict[str, Any]] = Field(default_factory=list)
    notable_logs: List[Dict[str, Any]] = Field(default_factory=list)


class TraceEvidence(BaseModel):
    metadata: EvidenceSourceMetadata
    failed_traces: List[Dict[str, Any]] = Field(default_factory=list)
    slow_spans: List[Dict[str, Any]] = Field(default_factory=list)


class KubernetesEvidence(BaseModel):
    metadata: EvidenceSourceMetadata
    events: List[Dict[str, Any]] = Field(default_factory=list)
    pod_statuses: List[Dict[str, Any]] = Field(default_factory=list)


class DerivedFact(BaseModel):
    fact: str = Field(min_length=1)
    evidence_paths: List[str] = Field(min_length=1)


class CollectorError(BaseModel):
    source: str
    error: str
    occurred_at: datetime


class MissingEvidenceItem(BaseModel):
    source: str
    reason: str
    impact: Optional[str] = None


class IncidentEvidenceBundle(BaseModel):
    schema_version: str = "1.0"
    incident: IncidentContextEvidence
    time_window: TimeWindowEvidence
    deployment: DeploymentEvidence
    pipeline: PipelineEvidence
    slo: SLOBreachEvidence
    metrics: MetricsEvidence
    logs: LogsEvidence
    traces: TraceEvidence
    kubernetes: KubernetesEvidence
    derived_facts: List[DerivedFact] = Field(default_factory=list)
    source_statuses: Dict[str, EvidenceSourceStatus] = Field(default_factory=dict)
    missing_sources: List[MissingEvidenceItem] = Field(default_factory=list)
    collector_errors: List[CollectorError] = Field(default_factory=list)
    completeness_score: float = Field(ge=0.0, le=1.0)
    
class SupportingEvidenceItem(BaseModel):
    observation: str = Field(min_length=1)
    evidence_path: str = Field(min_length=1)
    significance: str = Field(min_length=1)


class RecommendedAction(BaseModel):
    action: str = Field(min_length=1)
    priority: RecommendationPriority
    rationale: str = Field(min_length=1)


class AlternativeHypothesis(BaseModel):
    hypothesis: str = Field(min_length=1)
    supporting_evidence_paths: List[str] = Field(default_factory=list)
    contradicting_evidence_paths: List[str] = Field(default_factory=list)
    likelihood: RCAConfidence


class RCAMissingEvidenceItem(BaseModel):
    evidence: str = Field(min_length=1)
    source: Optional[str] = None
    impact: Optional[str] = None


class RCAOutputSchema(BaseModel):
    probable_root_cause: str = Field(min_length=1)
    root_cause_category: RootCauseCategory
    confidence: RCAConfidence
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_reason: str = Field(min_length=1)
    supporting_evidence: List[SupportingEvidenceItem] = Field(default_factory=list)
    recommended_actions: List[RecommendedAction] = Field(default_factory=list)
    alternative_hypotheses: List[AlternativeHypothesis] = Field(default_factory=list)
    missing_evidence: List[RCAMissingEvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def high_confidence_requires_supporting_evidence(self):
        if self.confidence == RCAConfidence.HIGH and not self.supporting_evidence:
            raise ValueError("HIGH confidence RCA requires supporting evidence")
        return self