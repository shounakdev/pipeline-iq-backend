"""Safety guardrails for remediation execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    ActionType,
    ApprovalDecision,
    Incident,
    IncidentStatus,
    RecommendationStatus,
    RecoveryVerificationStatus,
    RemediationRecommendation,
)
from app.remediation import repository
from app.remediation.config import (
    MAX_ROLLBACKS_PER_SERVICE_WINDOW,
    ROLLBACK_LOOP_PREVENTION_MINUTES,
    ROLLBACK_WINDOW_MINUTES,
)


class RemediationSafetyError(Exception):
    """Base exception for blocked remediation execution."""


class RemediationNotFoundError(
    RemediationSafetyError,
):
    pass


class RemediationServiceNotFoundError(
    RemediationSafetyError,
):
    pass


class RemediationIncidentNotFoundError(
    RemediationSafetyError,
):
    pass


class RemediationNotApprovedError(
    RemediationSafetyError,
):
    pass


class RejectedRemediationExecutionError(
    RemediationSafetyError,
):
    pass


class ResolvedIncidentExecutionError(
    RemediationSafetyError,
):
    pass


class DuplicateRemediationExecutionError(
    RemediationSafetyError,
):
    pass


class MaximumRollbackCountExceededError(
    RemediationSafetyError,
):
    pass


class RollbackTargetMissingError(
    RemediationSafetyError,
):
    pass


class DeploymentAlreadyRolledBackError(
    RemediationSafetyError,
):
    pass


class RollbackLoopDetectedError(
    RemediationSafetyError,
):
    pass


@dataclass(frozen=True)
class RemediationSafetyResult:
    recommendation: RemediationRecommendation
    incident: Incident
    rollback_count_in_window: int


def _clean_identifier(
    value: Any,
) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()

    return cleaned or None


def _rollback_deployment_key(
    recommendation: RemediationRecommendation,
) -> str | None:
    summary = (
        recommendation.evidence_summary
        if isinstance(
            recommendation.evidence_summary,
            dict,
        )
        else {}
    )

    for key in (
        "deployment_id",
        "suspected_deployment_id",
        "deployment_revision",
    ):
        value = _clean_identifier(
            summary.get(key),
        )

        if value is not None:
            return f"{key}:{value}"

    deployment = summary.get("deployment")

    if isinstance(deployment, dict):
        for key in (
            "id",
            "deployment_id",
            "revision",
            "deployment_revision",
        ):
            value = _clean_identifier(
                deployment.get(key),
            )

            if value is not None:
                return f"deployment:{value}"

    return None


def validate_execution_safety(
    *,
    db: Session,
    remediation_id: UUID,
    now: datetime | None = None,
) -> RemediationSafetyResult:
    checked_at = now or datetime.now(
        timezone.utc,
    )

    recommendation = repository.get_remediation_by_id(
        db,
        remediation_id,
        for_update=True,
    )

    if recommendation is None:
        raise RemediationNotFoundError(
            "Remediation recommendation was not found"
        )

    service = repository.get_service_by_id(
        db,
        recommendation.service_id,
        for_update=True,
    )

    if service is None:
        raise RemediationServiceNotFoundError(
            "The remediation service was not found"
        )

    incident = repository.get_incident_by_id(
        db,
        recommendation.incident_id,
        for_update=True,
    )

    if incident is None:
        raise RemediationIncidentNotFoundError(
            "The remediation incident was not found"
        )

    existing_execution = (
        repository.get_execution_by_remediation_id(
            db,
            recommendation.id,
        )
    )

    if existing_execution is not None:
        raise DuplicateRemediationExecutionError(
            "Remediation recommendation already has "
            "an execution"
        )

    approval = recommendation.approval

    if (
        recommendation.status
        == RecommendationStatus.REJECTED
        or (
            approval is not None
            and approval.decision
            == ApprovalDecision.REJECTED
        )
    ):
        raise RejectedRemediationExecutionError(
            "Rejected remediation cannot be executed"
        )

    if (
        recommendation.status
        != RecommendationStatus.APPROVED
        or approval is None
        or approval.decision
        != ApprovalDecision.APPROVED
    ):
        raise RemediationNotApprovedError(
            "Remediation requires approval before execution"
        )

    if incident.status == IncidentStatus.RESOLVED:
        raise ResolvedIncidentExecutionError(
            "Resolved incident cannot execute remediation"
        )

    if (
        recommendation.action_type
        != ActionType.ROLLBACK_DEPLOYMENT
    ):
        return RemediationSafetyResult(
            recommendation=recommendation,
            incident=incident,
            rollback_count_in_window=0,
        )

    rollback_window_start = checked_at - timedelta(
        minutes=ROLLBACK_WINDOW_MINUTES,
    )
    loop_window_start = checked_at - timedelta(
        minutes=ROLLBACK_LOOP_PREVENTION_MINUTES,
    )

    recent_rollbacks = (
        repository.list_recent_rollback_executions(
            db,
            service_id=recommendation.service_id,
            since=loop_window_start,
        )
    )

    rollback_count = sum(
        1
        for execution, _past_recommendation
        in recent_rollbacks
        if execution.created_at
        >= rollback_window_start
    )

    if (
        rollback_count
        >= MAX_ROLLBACKS_PER_SERVICE_WINDOW
    ):
        raise MaximumRollbackCountExceededError(
            "Maximum rollback count reached for "
            "the service within the configured window"
        )

    current_deployment_key = (
        _rollback_deployment_key(
            recommendation,
        )
    )

    if current_deployment_key is None:
        raise RollbackTargetMissingError(
            "Rollback recommendation does not identify "
            "the deployment being rolled back"
        )

    for execution, past_recommendation in recent_rollbacks:
        past_deployment_key = (
            _rollback_deployment_key(
                past_recommendation,
            )
        )

        if (
            past_deployment_key
            == current_deployment_key
        ):
            raise DeploymentAlreadyRolledBackError(
                "The same deployment was already "
                "rolled back recently"
            )

        verification = (
            repository
            .get_recovery_verification_for_execution(
                db,
                execution.id,
            )
        )

        if (
            verification is None
            or verification.verification_status
            != RecoveryVerificationStatus.VERIFIED
        ):
            raise RollbackLoopDetectedError(
                "Another rollback is blocked because "
                "a recent rollback has not completed "
                "successful recovery verification"
            )

    return RemediationSafetyResult(
        recommendation=recommendation,
        incident=incident,
        rollback_count_in_window=rollback_count,
    )