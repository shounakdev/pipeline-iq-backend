from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    BenchmarkStatus,
    ChaosObservationType,
    ChaosRunStatus,
    ChaosScenarioType,
    DiagnosisRating,
)


class ExperimentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    scenario_type: ChaosScenarioType
    target_service_id: str = Field(min_length=1, max_length=36)
    target_environment: str = Field(min_length=1, max_length=100)
    target_namespace: str = Field(min_length=1, max_length=255)
    failure_config: dict
    expected_behavior: dict
    enabled: bool = True

    @model_validator(mode="after")
    def validate_failure_duration(self):
        duration = self.failure_config.get("duration_seconds")
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration <= 0
        ):
            raise ValueError(
                "failure_config.duration_seconds must be a positive integer"
            )
        return self


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    scenario_type: ChaosScenarioType
    target_service_id: str
    target_environment: str
    target_namespace: str
    failure_type: str
    failure_config: dict
    expected_behavior: dict
    enabled: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class ChaosObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chaos_run_id: UUID
    observation_type: ChaosObservationType
    source: str
    observed_at: datetime
    resource_type: str | None
    resource_id: str | None
    details: dict
    created_at: datetime


class ExperimentBenchmarkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chaos_run_id: UUID
    failure_injection_timestamp: datetime | None
    first_anomaly_timestamp: datetime | None
    alert_creation_timestamp: datetime | None
    incident_creation_timestamp: datetime | None
    rca_completion_timestamp: datetime | None
    remediation_approval_timestamp: datetime | None
    recovery_completion_timestamp: datetime | None
    time_to_detect_ms: int | None
    time_to_alert_ms: int | None
    time_to_incident_ms: int | None
    time_to_diagnose_ms: int | None
    time_to_approve_ms: int | None
    time_to_recover_ms: int | None
    diagnosis_rating: DiagnosisRating
    expected_root_cause: str | None
    actual_root_cause: str | None
    detection_succeeded: bool | None
    recovery_succeeded: bool | None
    benchmark_status: BenchmarkStatus
    calculated_at: datetime


class ChaosRunCreateRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    environment: str = Field(min_length=1, max_length=100)
    namespace: str = Field(min_length=1, max_length=255)
    service: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    duration_seconds: int = Field(
        alias="durationSeconds",
        gt=0,
    )
    cleanup_behavior: Literal["delete"] = Field(
        alias="cleanupBehavior",
    )


class ChaosRunResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )

    id: UUID
    experiment_id: UUID
    status: ChaosRunStatus
    target_environment: str
    target_service_id: str
    target_namespace: str
    duration_seconds: int
    cleanup_behavior: str
    deadline_at: datetime
    kubernetes_resource_kind: str | None
    kubernetes_resource_name: str | None
    cleanup_succeeded: bool | None
    failure_message: str | None


class ExperimentRunResponse(ChaosRunResponse):
    triggered_by: str | None
    started_at: datetime | None
    failure_injected_at: datetime | None
    completed_at: datetime | None
    aborted_at: datetime | None
    incident_id: UUID | None
    rca_report_id: UUID | None
    remediation_id: UUID | None
    remediation_execution_id: UUID | None
    recovery_verification_id: UUID | None
    observations: list[ChaosObservationResponse] = Field(default_factory=list)
    benchmark: ExperimentBenchmarkResponse | None = None


class ExperimentRunQueuedResponse(BaseModel):
    run_id: UUID
    experiment_id: UUID
    status: ChaosRunStatus
    message: str


class ChaosCleanupResponse(BaseModel):
    run_id: UUID
    status: ChaosRunStatus
    cleanup_succeeded: bool