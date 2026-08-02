from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.models import (
    ActionType,
    ApprovalDecision,
    RCAConfidence,
    RecommendationStatus,
    RecoveryVerificationStatus,
    RemediationExecutionStatus,
)

class RemediationRecommendationCreate(BaseModel):
    incident_id: UUID
    service_id: str = Field(
        min_length=1,
        max_length=36,
    )
    environment: str = Field(
        min_length=1,
        max_length=100,
    )
    action_type: ActionType
    reason: str = Field(min_length=1)
    evidence_summary: dict[str, Any] = Field(
        default_factory=dict,
    )
    confidence: RCAConfidence
    created_by: str | None = Field(
        default=None,
        max_length=36,
    )


class RemediationRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    service_id: str
    environment: str
    action_type: ActionType
    reason: str
    evidence_summary: dict[str, Any]
    confidence: RCAConfidence
    status: RecommendationStatus
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class RecommendationEvaluationResponse(BaseModel):
    recommendation_created: bool
    recommendation: (
        RemediationRecommendationResponse | None
    ) = None
    message: str


class RemediationRejectionRequest(BaseModel):
    rejection_reason: str = Field(
        min_length=1,
        max_length=2000,
    )

    @field_validator("rejection_reason")
    @classmethod
    def validate_rejection_reason(
        cls,
        value: str,
    ) -> str:
        cleaned_value = value.strip()

        if not cleaned_value:
            raise ValueError(
                "Rejection reason must not be empty"
            )

        return cleaned_value


class RemediationApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    remediation_id: UUID
    approved_by: str | None
    decision: ApprovalDecision
    rejection_reason: str | None
    approved_at: datetime


class RemediationStatusResponse(
    RemediationRecommendationResponse,
):
    approval: RemediationApprovalResponse | None = None
    
class RemediationExecutionResponse(BaseModel):
    execution_id: UUID
    remediation_id: UUID
    action_type: ActionType
    command_type: str
    status: str
    message: str
    target_revision: str | None = None
    target_pod: str | None = None
    replica_count: int | None = None
    simulated: bool
    started_at: datetime
    completed_at: datetime
    
class RecoveryVerificationResponse(BaseModel):
    verification_id: UUID
    remediation_id: UUID
    execution_id: UUID
    status: RecoveryVerificationStatus
    recovered: bool
    error_rate_recovered: bool
    latency_recovered: bool
    pods_healthy: bool
    restart_loop_absent: bool
    availability_restored: bool
    metrics_snapshot: dict[str, Any]
    verified_at: datetime
    
class RemediationExecutionRecordResponse(BaseModel):
    """Persisted remediation execution information."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    remediation_id: UUID
    command_type: ActionType
    command_payload: dict[str, Any]
    execution_status: RemediationExecutionStatus
    started_at: datetime | None
    completed_at: datetime | None
    result_summary: dict[str, Any]
    error_message: str | None
    created_at: datetime


class RecoveryVerificationRecordResponse(BaseModel):
    """Persisted recovery-verification information."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    remediation_id: UUID
    remediation_execution_id: UUID
    verification_status: RecoveryVerificationStatus
    error_rate_recovered: bool
    latency_recovered: bool
    pods_healthy: bool
    restart_loop_absent: bool
    availability_restored: bool
    metrics_snapshot: dict[str, Any]
    verified_at: datetime


class RemediationAuditEventResponse(BaseModel):
    """Audit-history entry associated with a remediation."""

    id: str
    actor_id: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any]
    created_at: datetime


class RemediationDetailResponse(
    RemediationStatusResponse,
):
    """Complete read-only remediation workflow state."""

    execution: (
        RemediationExecutionRecordResponse | None
    ) = None

    verification: (
        RecoveryVerificationRecordResponse | None
    ) = None

    audit_history: list[
        RemediationAuditEventResponse
    ] = Field(default_factory=list)