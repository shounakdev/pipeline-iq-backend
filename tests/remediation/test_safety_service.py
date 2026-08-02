from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import (
    ActionType,
    ApprovalDecision,
    Incident,
    IncidentStatus,
    Project,
    RCAConfidence,
    RecoveryVerification,
    RecoveryVerificationStatus,
    RemediationApproval,
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationRecommendation,
    RecommendationStatus,
    Service,
    User,
)
from app.remediation.services.safety_service import (
    DeploymentAlreadyRolledBackError,
    DuplicateRemediationExecutionError,
    MaximumRollbackCountExceededError,
    RejectedRemediationExecutionError,
    ResolvedIncidentExecutionError,
    RollbackLoopDetectedError,
    validate_execution_safety,
)


def create_service_context(
    db_session,
):
    user = User(
        id=str(uuid4()),
        email=f"sprint9d-{uuid4()}@example.com",
        password_hash="test-password-hash",
        full_name="Sprint 9D Operator",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    project = Project(
        id=str(uuid4()),
        name=f"Sprint 9D Project {uuid4()}",
        description="Project for remediation safety tests.",
        created_by=user.id,
    )
    db_session.add(project)
    db_session.flush()

    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name=f"payment-service-{uuid4()}",
        description="Service for remediation safety tests.",
        service_type="BACKEND",
        owner="platform-team",
    )
    db_session.add(service)
    db_session.flush()

    return user, service


def create_decided_recommendation(
    db_session,
    *,
    user: User,
    service: Service,
    deployment_revision: str,
    status: RecommendationStatus = (
        RecommendationStatus.APPROVED
    ),
    incident_status: IncidentStatus = (
        IncidentStatus.DETECTED
    ),
) -> tuple[
    Incident,
    RemediationRecommendation,
]:
    now = datetime.now(timezone.utc)

    incident = Incident(
        title=f"Reliability regression {uuid4()}",
        description="Error rate increased after deployment.",
        primary_service_id=service.id,
        environment="staging",
        status=incident_status,
        resolved_at=(
            now
            if incident_status == IncidentStatus.RESOLVED
            else None
        ),
        created_by=user.id,
    )
    db_session.add(incident)
    db_session.flush()

    recommendation = RemediationRecommendation(
        incident_id=incident.id,
        service_id=service.id,
        environment="staging",
        action_type=ActionType.ROLLBACK_DEPLOYMENT,
        reason="Deployment caused a reliability regression.",
        evidence_summary={
            "rule_code": "RECENT_DEPLOYMENT_REGRESSION",
            "deployment_revision": deployment_revision,
            "previous_revision": "v1.8.1",
        },
        confidence=RCAConfidence.HIGH,
        status=status,
        created_by=user.id,
    )
    db_session.add(recommendation)
    db_session.flush()

    decision = (
        ApprovalDecision.REJECTED
        if status == RecommendationStatus.REJECTED
        else ApprovalDecision.APPROVED
    )

    approval = RemediationApproval(
        remediation_id=recommendation.id,
        approved_by=user.id,
        decision=decision,
        rejection_reason=(
            "Rollback was rejected by the operator."
            if decision == ApprovalDecision.REJECTED
            else None
        ),
    )
    db_session.add(approval)
    db_session.flush()

    return incident, recommendation


def create_execution(
    db_session,
    *,
    recommendation: RemediationRecommendation,
    created_at: datetime,
    verified: bool = False,
) -> RemediationExecution:
    execution = RemediationExecution(
        remediation_id=recommendation.id,
        command_type=ActionType.ROLLBACK_DEPLOYMENT,
        command_payload={
            "target_revision": "v1.8.1",
        },
        execution_status=(
            RemediationExecutionStatus.SUCCEEDED
        ),
        started_at=created_at,
        completed_at=created_at,
        result_summary={
            "provider": "argocd",
            "accepted": True,
        },
        created_at=created_at,
    )
    db_session.add(execution)
    db_session.flush()

    if verified:
        verification = RecoveryVerification(
            remediation_id=recommendation.id,
            remediation_execution_id=execution.id,
            verification_status=(
                RecoveryVerificationStatus.VERIFIED
            ),
            error_rate_recovered=True,
            latency_recovered=True,
            pods_healthy=True,
            restart_loop_absent=True,
            availability_restored=True,
            metrics_snapshot={
                "error_rate": 0.2,
                "p95_latency_ms": 180,
            },
            verified_at=created_at,
        )
        db_session.add(verification)
        db_session.flush()

    return execution


def test_rollback_loop_is_prevented(
    db_session,
) -> None:
    now = datetime.now(timezone.utc)
    user, service = create_service_context(
        db_session,
    )

    _past_incident, past_recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v1.8.0",
        )
    )

    create_execution(
        db_session,
        recommendation=past_recommendation,
        created_at=now - timedelta(minutes=30),
        verified=False,
    )

    _incident, current_recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v1.9.0",
        )
    )

    with pytest.raises(
        RollbackLoopDetectedError,
    ):
        validate_execution_safety(
            db=db_session,
            remediation_id=current_recommendation.id,
            now=now,
        )


def test_maximum_rollback_count_is_enforced(
    db_session,
) -> None:
    now = datetime.now(timezone.utc)
    user, service = create_service_context(
        db_session,
    )

    for minutes_ago, revision in (
        (10, "v1.7.0"),
        (20, "v1.8.0"),
    ):
        _incident, recommendation = (
            create_decided_recommendation(
                db_session,
                user=user,
                service=service,
                deployment_revision=revision,
            )
        )

        create_execution(
            db_session,
            recommendation=recommendation,
            created_at=(
                now - timedelta(
                    minutes=minutes_ago,
                )
            ),
            verified=True,
        )

    _incident, current_recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v1.9.0",
        )
    )

    with pytest.raises(
        MaximumRollbackCountExceededError,
    ):
        validate_execution_safety(
            db=db_session,
            remediation_id=current_recommendation.id,
            now=now,
        )


def test_duplicate_execution_is_blocked(
    db_session,
) -> None:
    now = datetime.now(timezone.utc)
    user, service = create_service_context(
        db_session,
    )

    _incident, recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v1.8.2",
        )
    )

    create_execution(
        db_session,
        recommendation=recommendation,
        created_at=now,
    )

    with pytest.raises(
        DuplicateRemediationExecutionError,
    ):
        validate_execution_safety(
            db=db_session,
            remediation_id=recommendation.id,
            now=now,
        )


def test_resolved_incident_cannot_execute_remediation(
    db_session,
) -> None:
    now = datetime.now(timezone.utc)
    user, service = create_service_context(
        db_session,
    )

    _incident, recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v1.8.2",
            incident_status=IncidentStatus.RESOLVED,
        )
    )

    with pytest.raises(
        ResolvedIncidentExecutionError,
    ):
        validate_execution_safety(
            db=db_session,
            remediation_id=recommendation.id,
            now=now,
        )


def test_rejected_remediation_cannot_execute(
    db_session,
) -> None:
    now = datetime.now(timezone.utc)
    user, service = create_service_context(
        db_session,
    )

    _incident, recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v1.8.2",
            status=RecommendationStatus.REJECTED,
        )
    )

    with pytest.raises(
        RejectedRemediationExecutionError,
    ):
        validate_execution_safety(
            db=db_session,
            remediation_id=recommendation.id,
            now=now,
        )


def test_same_deployment_cannot_be_rolled_back_again(
    db_session,
) -> None:
    now = datetime.now(timezone.utc)
    user, service = create_service_context(
        db_session,
    )

    _past_incident, past_recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v1.8.2",
        )
    )

    create_execution(
        db_session,
        recommendation=past_recommendation,
        created_at=now - timedelta(minutes=30),
        verified=True,
    )

    _incident, current_recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v1.8.2",
        )
    )

    with pytest.raises(
        DeploymentAlreadyRolledBackError,
    ):
        validate_execution_safety(
            db=db_session,
            remediation_id=current_recommendation.id,
            now=now,
        )
