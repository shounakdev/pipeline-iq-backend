from __future__ import annotations

import json
from typing import Any
from uuid import UUID
from datetime import datetime



from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ActionType,
    ApprovalDecision,
    AuditEvent,
    Deployment,
    Incident,
    IncidentEvidence,
    RCAReport,
    RecommendationStatus,
    RemediationApproval,
    RemediationRecommendation,
    RemediationExecutionStatus,
    ServiceHealthSnapshot,
    RecoveryVerification,
    RecoveryVerificationStatus,
    RemediationExecution,
    Service,
)
from app.remediation.schemas import (
    RemediationRecommendationCreate,
)


ACTIVE_RECOMMENDATION_STATUSES = {
    RecommendationStatus.PENDING_APPROVAL,
    RecommendationStatus.APPROVED,
}


def get_incident_by_id(
    db: Session,
    incident_id: UUID,
    *,
    for_update: bool = False,
) -> Incident | None:
    statement = select(Incident).where(
        Incident.id == incident_id,
    )

    if for_update:
        statement = statement.with_for_update()

    return db.execute(statement).scalar_one_or_none()


def get_latest_incident_evidence(
    db: Session,
    incident_id: UUID,
) -> IncidentEvidence | None:
    statement = (
        select(IncidentEvidence)
        .where(
            IncidentEvidence.incident_id
            == incident_id,
        )
        .order_by(
            IncidentEvidence.version.desc(),
            IncidentEvidence.created_at.desc(),
        )
        .limit(1)
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()


def get_latest_rca_report(
    db: Session,
    incident_id: UUID,
) -> RCAReport | None:
    statement = (
        select(RCAReport)
        .where(
            RCAReport.incident_id == incident_id,
        )
        .order_by(
            RCAReport.version.desc(),
            RCAReport.created_at.desc(),
        )
        .limit(1)
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()


def get_deployment_by_id(
    db: Session,
    deployment_id: UUID,
) -> Deployment | None:
    statement = select(Deployment).where(
        Deployment.id == deployment_id,
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()


def get_latest_service_health(
    db: Session,
    *,
    service_id: str,
    environment: str,
) -> ServiceHealthSnapshot | None:
    statement = (
        select(ServiceHealthSnapshot)
        .where(
            ServiceHealthSnapshot.service_id
            == service_id,
            func.lower(
                ServiceHealthSnapshot.environment,
            )
            == environment.strip().lower(),
        )
        .order_by(
            ServiceHealthSnapshot.created_at.desc(),
            ServiceHealthSnapshot.id.desc(),
        )
        .limit(1)
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()


def get_service_health_history(
    db: Session,
    *,
    service_id: str,
    environment: str,
    limit: int = 5,
) -> list[ServiceHealthSnapshot]:
    if limit <= 0:
        return []

    statement = (
        select(ServiceHealthSnapshot)
        .where(
            ServiceHealthSnapshot.service_id
            == service_id,
            func.lower(
                ServiceHealthSnapshot.environment,
            )
            == environment.strip().lower(),
        )
        .order_by(
            ServiceHealthSnapshot.created_at.desc(),
            ServiceHealthSnapshot.id.desc(),
        )
        .limit(limit)
    )

    return list(
        db.scalars(statement).all(),
    )


def get_active_recommendation(
    db: Session,
    *,
    incident_id: UUID,
    action_type: ActionType,
) -> RemediationRecommendation | None:
    statement = (
        select(RemediationRecommendation)
        .where(
            RemediationRecommendation.incident_id
            == incident_id,
            RemediationRecommendation.action_type
            == action_type,
            RemediationRecommendation.status.in_(
                ACTIVE_RECOMMENDATION_STATUSES,
            ),
        )
        .order_by(
            RemediationRecommendation.created_at.desc(),
            RemediationRecommendation.id.desc(),
        )
        .limit(1)
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()


def get_latest_recommendation(
    db: Session,
    incident_id: UUID,
) -> RemediationRecommendation | None:
    statement = (
        select(RemediationRecommendation)
        .where(
            RemediationRecommendation.incident_id
            == incident_id,
        )
        .order_by(
            RemediationRecommendation.created_at.desc(),
            RemediationRecommendation.id.desc(),
        )
        .limit(1)
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()


def recommendation_uses_source_snapshot(
    recommendation: RemediationRecommendation,
    *,
    evidence_id: UUID,
    rca_report_id: UUID,
) -> bool:
    summary = (
        recommendation.evidence_summary
        if isinstance(
            recommendation.evidence_summary,
            dict,
        )
        else {}
    )

    stored_evidence_id = (
        summary.get("incident_evidence_id")
        or summary.get("evidence_id")
    )
    stored_report_id = summary.get(
        "rca_report_id",
    )

    return (
        str(stored_evidence_id)
        == str(evidence_id)
        and str(stored_report_id)
        == str(rca_report_id)
    )


def create_recommendation(
    db: Session,
    recommendation_data: (
        RemediationRecommendationCreate
    ),
) -> RemediationRecommendation:
    recommendation = RemediationRecommendation(
        incident_id=(
            recommendation_data.incident_id
        ),
        service_id=(
            recommendation_data.service_id
        ),
        environment=(
            recommendation_data.environment
        ),
        action_type=(
            recommendation_data.action_type
        ),
        reason=recommendation_data.reason,
        evidence_summary=(
            recommendation_data.evidence_summary
        ),
        confidence=(
            recommendation_data.confidence
        ),
        created_by=(
            recommendation_data.created_by
        ),
    )

    db.add(recommendation)
    db.flush()
    db.refresh(recommendation)

    return recommendation


def create_recommendation_audit_event(
    db: Session,
    *,
    recommendation: RemediationRecommendation,
    requested_by: str | None,
) -> AuditEvent:
    summary = (
        recommendation.evidence_summary
        if isinstance(
            recommendation.evidence_summary,
            dict,
        )
        else {}
    )

    details: dict[str, Any] = {
        "actor_type": "SYSTEM",
        "requested_by": requested_by,
        "incident_id": str(
            recommendation.incident_id,
        ),
        "action_type": getattr(
            recommendation.action_type,
            "value",
            recommendation.action_type,
        ),
        "rule_code": summary.get("rule_code"),
        "requires_approval": True,
    }

    audit_event = AuditEvent(
        actor_id=requested_by,
        action="REMEDIATION_RECOMMENDED",
        entity_type="RemediationRecommendation",
        entity_id=str(recommendation.id),
        details=json.dumps(
            details,
            default=str,
            sort_keys=True,
        ),
    )

    db.add(audit_event)
    db.flush()

    return audit_event

def list_incident_remediations(
    db: Session,
    incident_id: UUID,
) -> list[RemediationRecommendation]:
    statement = (
        select(RemediationRecommendation)
        .where(
            RemediationRecommendation.incident_id
            == incident_id,
        )
        .order_by(
            RemediationRecommendation.created_at.desc(),
            RemediationRecommendation.id.desc(),
        )
    )

    return list(
        db.scalars(statement).all(),
    )
    
def list_all_remediations(
    db: Session,
) -> list[RemediationRecommendation]:
    """Return all remediation recommendations newest first."""

    statement = (
        select(RemediationRecommendation)
        .order_by(
            RemediationRecommendation.created_at.desc(),
            RemediationRecommendation.id.desc(),
        )
    )

    return list(
        db.scalars(statement).all(),
    )


def list_remediation_audit_events(
    db: Session,
    remediation_id: UUID,
) -> list[AuditEvent]:
    """Return audit history for one remediation."""

    statement = (
        select(AuditEvent)
        .where(
            AuditEvent.entity_type
            == "RemediationRecommendation",
            AuditEvent.entity_id
            == str(remediation_id),
        )
        .order_by(
            AuditEvent.created_at.asc(),
            AuditEvent.id.asc(),
        )
    )

    return list(
        db.scalars(statement).all(),
    )


def get_remediation_by_id(
    db: Session,
    remediation_id: UUID,
    *,
    for_update: bool = False,
) -> RemediationRecommendation | None:
    statement = select(
        RemediationRecommendation,
    ).where(
        RemediationRecommendation.id
        == remediation_id,
    )

    if for_update:
        statement = statement.with_for_update()

    return db.execute(
        statement,
    ).scalar_one_or_none()
    
def get_service_by_id(
    db: Session,
    service_id: str,
    *,
    for_update: bool = False,
) -> Service | None:
    statement = select(Service).where(
        Service.id == service_id,
    )

    if for_update:
        statement = statement.with_for_update()

    return db.execute(
        statement,
    ).scalar_one_or_none()


def get_execution_by_remediation_id(
    db: Session,
    remediation_id: UUID,
) -> RemediationExecution | None:
    statement = (
        select(RemediationExecution)
        .where(
            RemediationExecution.remediation_id
            == remediation_id,
        )
        .limit(1)
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()
    
def create_remediation_execution(
    db: Session,
    *,
    remediation: RemediationRecommendation,
    command_payload: dict[str, Any],
    started_at: datetime,
) -> RemediationExecution:
    execution = RemediationExecution(
        remediation_id=remediation.id,
        command_type=remediation.action_type,
        command_payload=command_payload,
        execution_status=(
            RemediationExecutionStatus.IN_PROGRESS
        ),
        started_at=started_at,
        result_summary={},
    )

    remediation.status = RecommendationStatus.EXECUTING

    db.add(execution)
    db.flush()
    db.refresh(execution)

    return execution


def complete_remediation_execution(
    db: Session,
    *,
    remediation: RemediationRecommendation,
    execution: RemediationExecution,
    result_summary: dict[str, Any],
    completed_at: datetime,
) -> RemediationExecution:
    execution.execution_status = (
        RemediationExecutionStatus.SUCCEEDED
    )
    execution.result_summary = result_summary
    execution.completed_at = completed_at
    execution.error_message = None

    remediation.status = RecommendationStatus.COMPLETED

    db.flush()
    db.refresh(execution)

    return execution


def fail_remediation_execution(
    db: Session,
    *,
    remediation: RemediationRecommendation,
    execution: RemediationExecution,
    error_message: str,
    completed_at: datetime,
) -> RemediationExecution:
    execution.execution_status = (
        RemediationExecutionStatus.FAILED
    )
    execution.completed_at = completed_at
    execution.error_message = error_message
    execution.result_summary = {
        "status": "FAILED",
        "message": error_message,
    }

    remediation.status = RecommendationStatus.FAILED

    db.flush()
    db.refresh(execution)

    return execution


def list_recent_rollback_executions(
    db: Session,
    *,
    service_id: str,
    since: datetime,
) -> list[
    tuple[
        RemediationExecution,
        RemediationRecommendation,
    ]
]:
    statement = (
        select(
            RemediationExecution,
            RemediationRecommendation,
        )
        .join(
            RemediationRecommendation,
            RemediationRecommendation.id
            == RemediationExecution.remediation_id,
        )
        .where(
            RemediationRecommendation.service_id
            == service_id,
            RemediationRecommendation.action_type
            == ActionType.ROLLBACK_DEPLOYMENT,
            RemediationExecution.created_at >= since,
        )
        .order_by(
            RemediationExecution.created_at.desc(),
            RemediationExecution.id.desc(),
        )
    )

    return [
        (
            execution,
            recommendation,
        )
        for execution, recommendation
        in db.execute(statement).all()
    ]


def get_recovery_verification_for_execution(
    db: Session,
    execution_id: UUID,
) -> RecoveryVerification | None:
    statement = (
        select(RecoveryVerification)
        .where(
            RecoveryVerification.remediation_execution_id
            == execution_id,
        )
        .limit(1)
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()
    
def get_latest_service_health_after(
    db: Session,
    *,
    service_id: str,
    environment: str,
    observed_after: datetime,
) -> ServiceHealthSnapshot | None:
    statement = (
        select(ServiceHealthSnapshot)
        .where(
            ServiceHealthSnapshot.service_id
            == service_id,
            func.lower(
                ServiceHealthSnapshot.environment,
            )
            == environment.strip().lower(),
            ServiceHealthSnapshot.created_at
            >= observed_after,
        )
        .order_by(
            ServiceHealthSnapshot.created_at.desc(),
            ServiceHealthSnapshot.id.desc(),
        )
        .limit(1)
    )

    return db.execute(
        statement,
    ).scalar_one_or_none()


def create_recovery_verification(
    db: Session,
    *,
    remediation: RemediationRecommendation,
    execution: RemediationExecution,
    verification_status: RecoveryVerificationStatus,
    error_rate_recovered: bool,
    latency_recovered: bool,
    pods_healthy: bool,
    restart_loop_absent: bool,
    availability_restored: bool,
    metrics_snapshot: dict[str, Any],
    verified_at: datetime,
) -> RecoveryVerification:
    verification = RecoveryVerification(
        remediation_id=remediation.id,
        remediation_execution_id=execution.id,
        verification_status=verification_status,
        error_rate_recovered=error_rate_recovered,
        latency_recovered=latency_recovered,
        pods_healthy=pods_healthy,
        restart_loop_absent=restart_loop_absent,
        availability_restored=availability_restored,
        metrics_snapshot=metrics_snapshot,
        verified_at=verified_at,
    )

    remediation.status = (
        RecommendationStatus.RECOVERY_VERIFIED
        if verification_status
        == RecoveryVerificationStatus.VERIFIED
        else RecommendationStatus.RECOVERY_FAILED
    )

    db.add(verification)
    db.flush()
    db.refresh(verification)

    return verification


def create_remediation_decision(
    db: Session,
    *,
    remediation: RemediationRecommendation,
    approved_by: str,
    decision: ApprovalDecision,
    rejection_reason: str | None = None,
) -> RemediationApproval:
    approval = RemediationApproval(
        remediation_id=remediation.id,
        approved_by=approved_by,
        decision=decision,
        rejection_reason=rejection_reason,
    )

    remediation.status = (
        RecommendationStatus.APPROVED
        if decision == ApprovalDecision.APPROVED
        else RecommendationStatus.REJECTED
    )

    db.add(approval)
    db.flush()
    db.refresh(approval)

    return approval


def create_remediation_decision_audit_event(
    db: Session,
    *,
    remediation: RemediationRecommendation,
    approval: RemediationApproval,
) -> AuditEvent:
    decision_value = getattr(
        approval.decision,
        "value",
        approval.decision,
    )

    action = (
        "REMEDIATION_APPROVED"
        if approval.decision
        == ApprovalDecision.APPROVED
        else "REMEDIATION_REJECTED"
    )

    details: dict[str, Any] = {
        "actor_type": "HUMAN",
        "incident_id": str(
            remediation.incident_id,
        ),
        "service_id": str(
            remediation.service_id,
        ),
        "environment": remediation.environment,
        "action_type": getattr(
            remediation.action_type,
            "value",
            remediation.action_type,
        ),
        "decision": decision_value,
        "previous_status": (
            RecommendationStatus
            .PENDING_APPROVAL
            .value
        ),
        "new_status": getattr(
            remediation.status,
            "value",
            remediation.status,
        ),
        "rejection_reason": (
            approval.rejection_reason
        ),
        "approval_id": str(approval.id),
    }

    audit_event = AuditEvent(
        actor_id=approval.approved_by,
        action=action,
        entity_type="RemediationRecommendation",
        entity_id=str(remediation.id),
        details=json.dumps(
            details,
            default=str,
            sort_keys=True,
        ),
    )

    db.add(audit_event)
    db.flush()

    return audit_event