from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.events.constants import (
    REMEDIATION_APPROVED,
    REMEDIATION_COMMAND_CREATED,
    REMEDIATION_COMPLETED,
    REMEDIATION_FAILED,
    REMEDIATION_RECOMMENDED,
    REMEDIATION_REJECTED,
    ROLLBACK_COMPLETED,
    ROLLBACK_STARTED,
    RECOVERY_FAILED,
    RECOVERY_VERIFIED,
)
from app.models import ActionType
from app.events.outbox import create_outbox_event


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def create_remediation_recommended_event(
    *,
    db: Session,
    recommendation: Any,
) -> Any:
    evidence_summary = (
        recommendation.evidence_summary
        if isinstance(
            recommendation.evidence_summary,
            dict,
        )
        else {}
    )

    return create_outbox_event(
        db,
        event_type=REMEDIATION_RECOMMENDED,
        correlation_id=str(
            recommendation.incident_id,
        ),
        service_id=str(
            recommendation.service_id,
        ),
        environment=recommendation.environment,
        payload={
            "event_version": 1,
            "occurred_at": (
                recommendation.created_at.isoformat()
                if recommendation.created_at
                else None
            ),
            "rule_code": evidence_summary.get(
                "rule_code",
            ),
            "requires_human_approval": True,
            "recommendation_id": str(
                recommendation.id,
            ),
            "incident_id": str(
                recommendation.incident_id,
            ),
            "service_id": str(
                recommendation.service_id,
            ),
            "environment": (
                recommendation.environment
            ),
            "action_type": _enum_value(
                recommendation.action_type,
            ),
            "reason": recommendation.reason,
            "confidence": _enum_value(
                recommendation.confidence,
            ),
            "status": _enum_value(
                recommendation.status,
            ),
            "incident_evidence_id": (
                evidence_summary.get(
                    "incident_evidence_id",
                )
                or evidence_summary.get(
                    "evidence_id",
                )
            ),
            "rca_report_id": evidence_summary.get(
                "rca_report_id",
            ),
            "created_by": (
                recommendation.created_by
            ),
            "created_at": (
                recommendation.created_at.isoformat()
                if recommendation.created_at
                else None
            ),
            "advisory_only": True,
            "execution_requested": False,
        },
    )


def _create_remediation_decision_event(
    *,
    db: Session,
    recommendation: Any,
    approval: Any,
    event_type: str,
) -> Any:
    return create_outbox_event(
        db,
        event_type=event_type,
        correlation_id=str(
            recommendation.incident_id,
        ),
        service_id=str(
            recommendation.service_id,
        ),
        environment=recommendation.environment,
        payload={
            "event_version": 1,
            "occurred_at": (
                approval.approved_at.isoformat()
                if approval.approved_at
                else None
            ),
            "recommendation_id": str(
                recommendation.id,
            ),
            "approval_id": str(
                approval.id,
            ),
            "incident_id": str(
                recommendation.incident_id,
            ),
            "service_id": str(
                recommendation.service_id,
            ),
            "environment": (
                recommendation.environment
            ),
            "action_type": _enum_value(
                recommendation.action_type,
            ),
            "decision": _enum_value(
                approval.decision,
            ),
            "status": _enum_value(
                recommendation.status,
            ),
            "decided_by": approval.approved_by,
            "rejection_reason": (
                approval.rejection_reason
            ),
            "requires_human_approval": True,
            "human_decision_recorded": True,
            "approval_only": True,
            "execution_requested": False,
        },
    )


def create_remediation_approved_event(
    *,
    db: Session,
    recommendation: Any,
    approval: Any,
) -> Any:
    return _create_remediation_decision_event(
        db=db,
        recommendation=recommendation,
        approval=approval,
        event_type=REMEDIATION_APPROVED,
    )


def create_remediation_rejected_event(
    *,
    db: Session,
    recommendation: Any,
    approval: Any,
) -> Any:
    return _create_remediation_decision_event(
        db=db,
        recommendation=recommendation,
        approval=approval,
        event_type=REMEDIATION_REJECTED,
    )
    
def create_remediation_execution_started_event(
    *,
    db: Session,
    recommendation: Any,
    execution: Any,
) -> Any:
    event_type = (
        ROLLBACK_STARTED
        if recommendation.action_type
        == ActionType.ROLLBACK_DEPLOYMENT
        else REMEDIATION_COMMAND_CREATED
    )

    return create_outbox_event(
        db,
        event_type=event_type,
        correlation_id=str(
            recommendation.incident_id,
        ),
        service_id=str(
            recommendation.service_id,
        ),
        environment=recommendation.environment,
        payload={
            "event_version": 1,
            "occurred_at": (
                execution.started_at.isoformat()
                if execution.started_at
                else None
            ),
            "recommendation_id": str(
                recommendation.id,
            ),
            "execution_id": str(execution.id),
            "incident_id": str(
                recommendation.incident_id,
            ),
            "service_id": str(
                recommendation.service_id,
            ),
            "environment": (
                recommendation.environment
            ),
            "action_type": _enum_value(
                recommendation.action_type,
            ),
            "command_type": (
                execution.command_payload.get(
                    "command_type"
                )
            ),
            "command_payload": (
                execution.command_payload
            ),
            "execution_status": _enum_value(
                execution.execution_status,
            ),
        },
    )


def create_remediation_execution_completed_event(
    *,
    db: Session,
    recommendation: Any,
    execution: Any,
) -> Any:
    event_type = (
        ROLLBACK_COMPLETED
        if recommendation.action_type
        == ActionType.ROLLBACK_DEPLOYMENT
        else REMEDIATION_COMPLETED
    )

    return create_outbox_event(
        db,
        event_type=event_type,
        correlation_id=str(
            recommendation.incident_id,
        ),
        service_id=str(
            recommendation.service_id,
        ),
        environment=recommendation.environment,
        payload={
            "event_version": 1,
            "occurred_at": (
                execution.completed_at.isoformat()
                if execution.completed_at
                else None
            ),
            "recommendation_id": str(
                recommendation.id,
            ),
            "execution_id": str(execution.id),
            "incident_id": str(
                recommendation.incident_id,
            ),
            "service_id": str(
                recommendation.service_id,
            ),
            "environment": (
                recommendation.environment
            ),
            "action_type": _enum_value(
                recommendation.action_type,
            ),
            "command_type": (
                execution.result_summary.get(
                    "command_type"
                )
            ),
            "execution_status": _enum_value(
                execution.execution_status,
            ),
            "result": execution.result_summary,
        },
    )


def create_remediation_execution_failed_event(
    *,
    db: Session,
    recommendation: Any,
    execution: Any,
) -> Any:
    return create_outbox_event(
        db,
        event_type=REMEDIATION_FAILED,
        correlation_id=str(
            recommendation.incident_id,
        ),
        service_id=str(
            recommendation.service_id,
        ),
        environment=recommendation.environment,
        payload={
            "event_version": 1,
            "occurred_at": (
                execution.completed_at.isoformat()
                if execution.completed_at
                else None
            ),
            "recommendation_id": str(
                recommendation.id,
            ),
            "execution_id": str(execution.id),
            "action_type": _enum_value(
                recommendation.action_type,
            ),
            "execution_status": _enum_value(
                execution.execution_status,
            ),
            "error_message": execution.error_message,
        },
    )
def _create_recovery_verification_event(
    *,
    db: Session,
    recommendation: Any,
    execution: Any,
    verification: Any,
    event_type: str,
) -> Any:
    return create_outbox_event(
        db,
        event_type=event_type,
        correlation_id=str(
            recommendation.incident_id,
        ),
        service_id=str(
            recommendation.service_id,
        ),
        environment=recommendation.environment,
        payload={
            "event_version": 1,
            "occurred_at": (
                verification.verified_at.isoformat()
                if verification.verified_at
                else None
            ),
            "recommendation_id": str(
                recommendation.id,
            ),
            "execution_id": str(execution.id),
            "verification_id": str(
                verification.id,
            ),
            "incident_id": str(
                recommendation.incident_id,
            ),
            "service_id": str(
                recommendation.service_id,
            ),
            "environment": (
                recommendation.environment
            ),
            "action_type": _enum_value(
                recommendation.action_type,
            ),
            "verification_status": _enum_value(
                verification.verification_status,
            ),
            "error_rate_recovered": (
                verification.error_rate_recovered
            ),
            "latency_recovered": (
                verification.latency_recovered
            ),
            "pods_healthy": (
                verification.pods_healthy
            ),
            "restart_loop_absent": (
                verification.restart_loop_absent
            ),
            "availability_restored": (
                verification.availability_restored
            ),
            "metrics_snapshot": (
                verification.metrics_snapshot
            ),
        },
    )


def create_recovery_verified_event(
    *,
    db: Session,
    recommendation: Any,
    execution: Any,
    verification: Any,
) -> Any:
    return _create_recovery_verification_event(
        db=db,
        recommendation=recommendation,
        execution=execution,
        verification=verification,
        event_type=RECOVERY_VERIFIED,
    )


def create_recovery_failed_event(
    *,
    db: Session,
    recommendation: Any,
    execution: Any,
    verification: Any,
) -> Any:
    return _create_recovery_verification_event(
        db=db,
        recommendation=recommendation,
        execution=execution,
        verification=verification,
        event_type=RECOVERY_FAILED,
    )