from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from app.models import (
    ErrorBudgetState,
    ReliabilityAlertStatus,
    ReliabilityAlertType,
    ReliabilitySeverity,
    SLOMetricType,
)


class SLOCreate(BaseModel):
    metric_type: SLOMetricType
    target_value: float
    window_minutes: int = Field(
        default=60,
        ge=1,
        le=10080,
    )
    severity_on_breach: ReliabilitySeverity = (
        ReliabilitySeverity.HIGH
    )
    enabled: bool = True

    @model_validator(mode="after")
    def validate_target_value(self):
        if self.metric_type == SLOMetricType.AVAILABILITY:
            if not 0 < self.target_value <= 100:
                raise ValueError(
                    "Availability target_value must be greater "
                    "than 0 and less than or equal to 100."
                )

        elif self.metric_type == SLOMetricType.ERROR_RATE:
            if not 0 <= self.target_value <= 100:
                raise ValueError(
                    "Error-rate target_value must be between "
                    "0 and 100."
                )

        elif self.metric_type == SLOMetricType.P95_LATENCY:
            if self.target_value <= 0:
                raise ValueError(
                    "P95 latency target_value must be greater "
                    "than 0 milliseconds."
                )

        return self


class SLOResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    service_id: str
    metric_type: SLOMetricType
    target_value: float
    window_minutes: int
    severity_on_breach: ReliabilitySeverity
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SLOEvaluationResponse(BaseModel):
    measurement_id: str
    slo_definition_id: str
    service_id: str
    service_name: str
    metric_type: SLOMetricType
    target_value: float
    measured_value: float
    is_breached: bool
    window_minutes: int
    source: str
    evaluated_at: datetime


class ReliabilitySLOStateResponse(BaseModel):
    slo_definition_id: str
    metric_type: SLOMetricType
    target_value: float
    measured_value: float | None = None
    status: Literal[
        "HEALTHY",
        "BREACHED",
        "NO_DATA",
    ]
    evaluated_at: datetime | None = None
    error_budget_state: ErrorBudgetState | None = None


class ReliabilityDeploymentResponse(BaseModel):
    id: str
    environment: str | None = None
    status: str | None = None
    created_at: datetime | None = None


class ReliabilityAlertResponse(BaseModel):
    id: str
    service_id: str
    slo_definition_id: str | None = None
    alert_type: ReliabilityAlertType
    severity: ReliabilitySeverity
    triggered_value: float
    threshold_value: float
    deployment_id: str | None = None
    status: ReliabilityAlertStatus
    created_at: datetime
    resolved_at: datetime | None = None


class ServiceReliabilityResponse(BaseModel):
    service_id: str
    service_name: str
    slos: list[ReliabilitySLOStateResponse]
    open_alerts: list[ReliabilityAlertResponse]
    latest_deployment: (
        ReliabilityDeploymentResponse | None
    ) = None


class ErrorBudgetItemResponse(BaseModel):
    slo_definition_id: str
    metric_type: SLOMetricType
    target_percentage: float
    remaining_percentage: float
    consumed_percentage: float
    burn_rate: float
    status: ErrorBudgetState
    evaluated_at: datetime


class ServiceErrorBudgetResponse(BaseModel):
    service_id: str
    budgets: list[ErrorBudgetItemResponse]


class ReliabilitySLODefinitionSummary(BaseModel):
    id: str
    service_id: str
    metric_type: SLOMetricType
    target_value: float
    window_minutes: int
    enabled: bool


class ReliabilityAlertDetailResponse(
    ReliabilityAlertResponse
):
    slo_definition: (
        ReliabilitySLODefinitionSummary | None
    ) = None

    deployment: (
        ReliabilityDeploymentResponse | None
    ) = None