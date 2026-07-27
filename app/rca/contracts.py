from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.rca.enums import (
    RCAConfidenceLevel,
    RCAEvidenceAvailability,
    RCAEvidenceSource,
)


class RCAEvidenceSourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: RCAEvidenceSource
    availability: RCAEvidenceAvailability
    collected_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class RCAEvidenceWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime


class RCAIncidentIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    incident_number: str
    title: str
    severity: str
    status: str
    service_id: str
    service_name: str | None = None
    environment: str
    failure_started_at: datetime | None = None
    detected_at: datetime
    acknowledged_at: datetime | None = None
    investigation_started_at: datetime | None = None
    remediation_started_at: datetime | None = None
    resolved_at: datetime | None = None


class RCADeterministicEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident: RCAIncidentIdentity
    evidence_window: RCAEvidenceWindow

    triggering_alert: dict[str, Any] | None = None
    linked_alerts: list[dict[str, Any]] = Field(default_factory=list)

    deployment: dict[str, Any] | None = None
    deployment_workloads: list[dict[str, Any]] = Field(default_factory=list)
    deployment_revisions: list[dict[str, Any]] = Field(default_factory=list)
    deployment_events: list[dict[str, Any]] = Field(default_factory=list)

    pipeline_run: dict[str, Any] | None = None
    pipeline_findings: dict[str, Any] | None = None
    pipeline_logs: list[dict[str, Any]] = Field(default_factory=list)

    service_health_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    prometheus_metrics: dict[str, Any] = Field(default_factory=dict)
    slo_measurements: list[dict[str, Any]] = Field(default_factory=list)
    error_budget_statuses: list[dict[str, Any]] = Field(default_factory=list)

    kubernetes_workloads: list[dict[str, Any]] = Field(default_factory=list)
    kubernetes_events: list[dict[str, Any]] = Field(default_factory=list)

    logs: list[dict[str, Any]] = Field(default_factory=list)
    failed_traces: list[dict[str, Any]] = Field(default_factory=list)

    incident_timeline: list[dict[str, Any]] = Field(default_factory=list)
    incident_metrics: list[dict[str, Any]] = Field(default_factory=list)

    source_statuses: list[RCAEvidenceSourceStatus] = Field(default_factory=list)


class RCAHumanContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[dict[str, Any]] = Field(default_factory=list)
    comments: list[dict[str, Any]] = Field(default_factory=list)


class RCAEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    collected_at: datetime
    deterministic: RCADeterministicEvidence
    human_context: RCAHumanContext = Field(default_factory=RCAHumanContext)


class RCACausalFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    explanation: str
    evidence_references: list[str] = Field(default_factory=list)
    confidence: RCAConfidenceLevel


class RCAReportContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_summary: str
    primary_root_cause: str
    contributing_factors: list[RCACausalFactor] = Field(default_factory=list)
    impact_summary: str
    evidence_summary: list[str] = Field(default_factory=list)
    remediation_actions: list[str] = Field(default_factory=list)
    prevention_actions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    overall_confidence: RCAConfidenceLevel
