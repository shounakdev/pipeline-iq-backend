from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.incidents.enums import (
    IncidentSeverity,
    IncidentStatus,
)
from app.schemas import RequestSchema, ResponseSchema


# ---------------------------------------------------------------------------
# Shared summary responses
# ---------------------------------------------------------------------------


class ServiceSummaryResponse(ResponseSchema):
    id: str
    name: str
    service_type: str | None = None
    owner: str | None = None


class OperatorSummaryResponse(ResponseSchema):
    id: str
    email: str
    full_name: str | None = None


class ReliabilityAlertSummaryResponse(ResponseSchema):
    id: str
    service_id: str
    slo_definition_id: str
    alert_type: str
    severity: str
    triggered_value: float
    threshold_value: float
    deployment_id: UUID | None = None
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


class DeploymentSummaryResponse(ResponseSchema):
    id: UUID
    service_id: str
    service_name: str | None = None
    environment_id: str | None = None
    image_tag: str
    deployment_version: str | None = None
    commit_sha: str | None = None
    argo_sync_status: str | None = None
    kubernetes_rollout_status: str | None = None
    deployed_at: datetime | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Timeline event responses
# ---------------------------------------------------------------------------


class IncidentTimelineEventResponse(ResponseSchema):
    id: UUID
    incident_id: UUID

    event_type: str
    source: str
    message: str | None = None

    from_status: IncidentStatus | None = None
    to_status: IncidentStatus | None = None

    actor_user_id: str | None = None
    actor: OperatorSummaryResponse | None = None

    alert_id: str | None = None
    alert: ReliabilityAlertSummaryResponse | None = None

    deployment_id: UUID | None = None
    deployment: DeploymentSummaryResponse | None = None

    metadata_json: dict[str, Any] | None = None

    occurred_at: datetime
    created_at: datetime


# ---------------------------------------------------------------------------
# Incident action requests
# ---------------------------------------------------------------------------


class IncidentAcknowledgeRequest(RequestSchema):
    note: str | None = Field(
        default=None,
        max_length=5000,
    )
    assign_to_self: bool = False

    @field_validator("note")
    @classmethod
    def reject_blank_note(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Note cannot be blank")

        return value


class IncidentAssignRequest(RequestSchema):
    assigned_to_user_id: str = Field(
        min_length=1,
        max_length=255,
    )
    note: str | None = Field(
        default=None,
        max_length=5000,
    )

    @field_validator("assigned_to_user_id")
    @classmethod
    def reject_blank_user_id(
        cls,
        value: str,
    ) -> str:
        if not value.strip():
            raise ValueError(
                "assigned_to_user_id cannot be blank"
            )

        return value

    @field_validator("note")
    @classmethod
    def reject_blank_note(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Note cannot be blank")

        return value


class IncidentStatusUpdateRequest(RequestSchema):
    status: IncidentStatus
    reason: str = Field(
        min_length=1,
        max_length=5000,
    )

    @field_validator("reason")
    @classmethod
    def reject_blank_reason(
        cls,
        value: str,
    ) -> str:
        if not value.strip():
            raise ValueError("Reason cannot be blank")

        return value


# Existing assignment request retained for compatibility with code that still
# uses assignment_note instead of the Sprint 7J note field.
class IncidentAssignmentRequest(RequestSchema):
    assigned_to_user_id: str = Field(
        min_length=1,
        max_length=36,
    )
    assignment_note: str | None = Field(
        default=None,
        max_length=4000,
    )

    @field_validator("assigned_to_user_id")
    @classmethod
    def reject_blank_user_id(
        cls,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "assigned_to_user_id cannot be blank"
            )

        return value

    @field_validator("assignment_note")
    @classmethod
    def reject_blank_assignment_note(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError(
                "Assignment note cannot be blank"
            )

        return value


class IncidentResolveRequest(RequestSchema):
    resolution_summary: str = Field(
        min_length=1,
        max_length=10_000,
    )
    note: str | None = Field(
        default=None,
        max_length=4000,
    )

    @field_validator("resolution_summary")
    @classmethod
    def validate_resolution_summary(
        cls,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "resolution_summary cannot be empty"
            )

        return value


# ---------------------------------------------------------------------------
# Assignment responses
# ---------------------------------------------------------------------------


class IncidentAssignmentResponse(ResponseSchema):
    id: UUID
    incident_id: UUID

    assigned_to_user_id: str | None = None
    assigned_to_user: OperatorSummaryResponse | None = None

    assigned_by_user_id: str | None = None
    assigned_by_user: OperatorSummaryResponse | None = None

    assignment_note: str | None = None

    assigned_at: datetime
    unassigned_at: datetime | None = None
    is_active: bool


# ---------------------------------------------------------------------------
# Comment requests and responses
# ---------------------------------------------------------------------------


class IncidentCommentCreateRequest(RequestSchema):
    comment: str = Field(
        min_length=1,
        max_length=10_000,
    )

    @field_validator("comment")
    @classmethod
    def reject_blank_comment(
        cls,
        value: str,
    ) -> str:
        if not value.strip():
            raise ValueError("Comment cannot be blank")

        return value


class IncidentCommentResponse(ResponseSchema):
    id: UUID
    incident_id: UUID

    author_user_id: str | None = None
    author: OperatorSummaryResponse | None = None

    comment: str

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Incident metric responses
# ---------------------------------------------------------------------------


class IncidentMetricResponse(ResponseSchema):
    id: UUID
    incident_id: UUID

    metric_type: str
    metric_name: str
    value: float
    unit: str | None = None
    source: str

    captured_at: datetime
    metadata_json: dict[str, Any] | None = None
    created_at: datetime


class IncidentCalculatedMetricsResponse(ResponseSchema):
    incident_id: UUID

    failure_started_at: datetime | None = None
    detected_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    mttd_seconds: float | None = Field(
        default=None,
        ge=0,
    )
    mtta_seconds: float | None = Field(
        default=None,
        ge=0,
    )
    mttr_seconds: float | None = Field(
        default=None,
        ge=0,
    )


class IncidentMetricsResponse(ResponseSchema):
    incident_id: UUID

    metric_snapshot: list[IncidentMetricResponse] = Field(
        default_factory=list,
    )

    mttd_seconds: int | None = None
    mtta_seconds: int | None = None
    mttr_seconds: int | None = None

    mttd_display: str | None = None
    mtta_display: str | None = None
    mttr_display: str | None = None

    alert_threshold: float | None = None
    triggered_value: float | None = None
    error_budget_status: str | None = None


class IncidentMetricsSummaryResponse(ResponseSchema):
    average_mttd_seconds: float | None
    average_mtta_seconds: float | None
    average_mttr_seconds: float | None

    average_mttd_display: str | None
    average_mtta_display: str | None
    average_mttr_display: str | None

    open_incident_count: int
    resolved_incident_count: int

    sev_1_incident_count: int
    sev_2_incident_count: int
    sev_3_incident_count: int


# ---------------------------------------------------------------------------
# Incident list and detail responses
# ---------------------------------------------------------------------------


class IncidentListItemResponse(ResponseSchema):
    incident_id: UUID

    # Temporary compatibility field for the current Sprint 5 frontend.
    # Both values will contain the same incident UUID.
    id: UUID | None = None

    incident_number: str
    title: str

    severity: IncidentSeverity
    status: IncidentStatus

    # These represent the primary_service_id relationship in a
    # frontend-friendly form.
    service_id: str
    service_name: str | None = None

    environment: str

    assigned_operator: OperatorSummaryResponse | None = None
    suspected_deployment_id: UUID | None = None

    failure_started_at: datetime | None = None
    detected_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    mttd_seconds: int | None = None
    mtta_seconds: int | None = None
    mttr_seconds: int | None = None

    mttd_display: str | None = None
    mtta_display: str | None = None
    mttr_display: str | None = None

    created_at: datetime
    updated_at: datetime


class IncidentListResponse(ResponseSchema):
    items: list[IncidentListItemResponse] = Field(
        default_factory=list,
    )
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def create(
        cls,
        *,
        items: list[IncidentListItemResponse],
        total: int,
        page: int,
        page_size: int,
    ) -> "IncidentListResponse":
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(
                math.ceil(total / page_size)
                if total > 0
                else 0
            ),
        )


class IncidentDetailResponse(ResponseSchema):
    incident: IncidentListItemResponse

    description: str | None = None
    deduplication_key: str

    primary_service: ServiceSummaryResponse
    affected_services: list[ServiceSummaryResponse] = Field(
        default_factory=list,
    )

    triggering_alert_id: str | None = None
    triggering_alert: ReliabilityAlertSummaryResponse | None = None

    related_alerts: list[ReliabilityAlertSummaryResponse] = Field(
        default_factory=list,
    )

    suspected_deployment: DeploymentSummaryResponse | None = None

    failure_started_at: datetime | None = None
    investigation_started_at: datetime | None = None
    remediation_started_at: datetime | None = None

    mttd_seconds: int | None = None
    mtta_seconds: int | None = None
    mttr_seconds: int | None = None

    mttd_display: str | None = None
    mtta_display: str | None = None
    mttr_display: str | None = None

    created_by: str | None = None
    creator: OperatorSummaryResponse | None = None

    current_assignment: IncidentAssignmentResponse | None = None

    assignment_history: list[IncidentAssignmentResponse] = Field(
        default_factory=list,
    )
    comments: list[IncidentCommentResponse] = Field(
        default_factory=list,
    )
    metric_snapshot: list[IncidentMetricResponse] = Field(
        default_factory=list,
    )
    timeline_summary: list[IncidentTimelineEventResponse] = Field(
        default_factory=list,
    )

    resolution_summary: str | None = None
    rca_summary: str | None = None
    remediation_summary: str | None = None

    calculated_incident_metrics: (
        IncidentCalculatedMetricsResponse | None
    ) = None


class IncidentTimelineResponse(ResponseSchema):
    incident_id: UUID
    events: list[IncidentTimelineEventResponse] = Field(
        default_factory=list,
    )