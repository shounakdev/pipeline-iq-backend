from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    ActionType,
    ApprovalDecision,
    Incident,
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


def create_remediation_context(
    db_session,
    *,
    action_type=ActionType.ROLLBACK_DEPLOYMENT,
):
    user = User(
        id=str(uuid4()),
        email=f"sprint9a-{uuid4()}@example.com",
        password_hash="test-password-hash",
        full_name="Sprint 9A Operator",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    project = Project(
        id=str(uuid4()),
        name=f"Sprint 9A Project {uuid4()}",
        description="Project used by remediation model tests.",
        created_by=user.id,
    )
    db_session.add(project)
    db_session.flush()

    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name=f"payment-service-{uuid4()}",
        description="Service used by remediation model tests.",
        service_type="BACKEND",
        owner="platform-team",
    )
    db_session.add(service)
    db_session.flush()

    incident = Incident(
        title="Payment service reliability regression",
        description="Error rate increased following deployment.",
        primary_service_id=service.id,
        environment="staging",
        created_by=user.id,
    )
    db_session.add(incident)
    db_session.flush()

    recommendation = RemediationRecommendation(
        incident_id=incident.id,
        service_id=service.id,
        environment="staging",
        action_type=action_type,
        reason="Deployment is temporally correlated with the incident.",
        evidence_summary={
            "probable_root_cause": "Deployment regression",
            "supporting_evidence": [
                "Error rate increased after deployment",
                "Previous revision was healthy",
            ],
        },
        confidence=RCAConfidence.HIGH,
        created_by=user.id,
    )
    db_session.add(recommendation)
    db_session.flush()

    return {
        "user": user,
        "project": project,
        "service": service,
        "incident": incident,
        "recommendation": recommendation,
    }


def test_remediation_recommendation_is_persisted_with_default_status(
    db_session,
):
    context = create_remediation_context(db_session)
    recommendation = context["recommendation"]

    recommendation_id = recommendation.id
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(
        RemediationRecommendation,
        recommendation_id,
    )

    assert stored is not None
    assert stored.incident_id == context["incident"].id
    assert stored.service_id == context["service"].id
    assert stored.environment == "staging"
    assert stored.action_type == ActionType.ROLLBACK_DEPLOYMENT
    assert stored.confidence == RCAConfidence.HIGH
    assert stored.status == RecommendationStatus.PENDING_APPROVAL
    assert stored.evidence_summary["probable_root_cause"] == (
        "Deployment regression"
    )
    assert stored.created_at is not None
    assert stored.updated_at is not None


@pytest.mark.parametrize(
    "action_type",
    [
        ActionType.ROLLBACK_DEPLOYMENT,
        ActionType.RESTART_POD,
        ActionType.SCALE_REPLICAS,
        ActionType.REDEPLOY_REVISION,
    ],
)
def test_all_supported_action_types_are_persisted(
    db_session,
    action_type,
):
    context = create_remediation_context(
        db_session,
        action_type=action_type,
    )

    recommendation_id = context["recommendation"].id
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(
        RemediationRecommendation,
        recommendation_id,
    )

    assert stored.action_type == action_type


def test_approved_decision_is_persisted(
    db_session,
):
    context = create_remediation_context(db_session)

    approval = RemediationApproval(
        remediation_id=context["recommendation"].id,
        approved_by=context["user"].id,
        decision=ApprovalDecision.APPROVED,
    )
    db_session.add(approval)
    db_session.commit()

    db_session.refresh(approval)

    assert approval.id is not None
    assert approval.decision == ApprovalDecision.APPROVED
    assert approval.rejection_reason is None
    assert approval.approved_at is not None
    assert approval.remediation.id == context["recommendation"].id
    assert approval.approver.id == context["user"].id


def test_rejected_decision_with_reason_is_persisted(
    db_session,
):
    context = create_remediation_context(db_session)

    approval = RemediationApproval(
        remediation_id=context["recommendation"].id,
        approved_by=context["user"].id,
        decision=ApprovalDecision.REJECTED,
        rejection_reason="Evidence is insufficient for a safe rollback.",
    )
    db_session.add(approval)
    db_session.commit()

    db_session.refresh(approval)

    assert approval.decision == ApprovalDecision.REJECTED
    assert approval.rejection_reason == (
        "Evidence is insufficient for a safe rollback."
    )


def test_rejected_decision_requires_rejection_reason(
    db_session,
):
    context = create_remediation_context(db_session)

    approval = RemediationApproval(
        remediation_id=context["recommendation"].id,
        approved_by=context["user"].id,
        decision=ApprovalDecision.REJECTED,
        rejection_reason=None,
    )
    db_session.add(approval)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_only_one_approval_is_allowed_per_recommendation(
    db_session,
):
    context = create_remediation_context(db_session)

    first_approval = RemediationApproval(
        remediation_id=context["recommendation"].id,
        approved_by=context["user"].id,
        decision=ApprovalDecision.APPROVED,
    )
    db_session.add(first_approval)
    db_session.flush()

    second_approval = RemediationApproval(
        remediation_id=context["recommendation"].id,
        approved_by=context["user"].id,
        decision=ApprovalDecision.REJECTED,
        rejection_reason="Second decision must not be stored.",
    )
    db_session.add(second_approval)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_only_one_execution_is_allowed_per_recommendation(
    db_session,
):
    context = create_remediation_context(db_session)
    recommendation = context["recommendation"]

    first_execution = RemediationExecution(
        remediation_id=recommendation.id,
        command_type=ActionType.ROLLBACK_DEPLOYMENT,
        command_payload={
            "namespace": "staging",
            "target_revision": "v1.8.1",
        },
        execution_status=(
            RemediationExecutionStatus.FAILED
        ),
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        result_summary={
            "provider": "argocd",
            "accepted": False,
        },
        error_message="Argo CD request timed out.",
    )

    db_session.add(first_execution)
    db_session.flush()

    second_execution = RemediationExecution(
        remediation_id=recommendation.id,
        command_type=ActionType.ROLLBACK_DEPLOYMENT,
        command_payload={
            "namespace": "staging",
            "target_revision": "v1.8.1",
        },
        execution_status=(
            RemediationExecutionStatus.PENDING
        ),
        result_summary={},
    )

    db_session.add(second_execution)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()

def test_execution_completed_at_cannot_precede_started_at(
    db_session,
):
    context = create_remediation_context(db_session)

    now = datetime.now(timezone.utc)

    execution = RemediationExecution(
        remediation_id=context["recommendation"].id,
        command_type=ActionType.ROLLBACK_DEPLOYMENT,
        command_payload={
            "target_revision": "v1.8.1",
        },
        execution_status=RemediationExecutionStatus.FAILED,
        started_at=now,
        completed_at=now - timedelta(minutes=1),
        result_summary={},
        error_message="Invalid timestamp test.",
    )
    db_session.add(execution)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_recovery_verification_is_persisted(
    db_session,
):
    context = create_remediation_context(db_session)

    now = datetime.now(timezone.utc)

    execution = RemediationExecution(
        remediation_id=context["recommendation"].id,
        command_type=ActionType.ROLLBACK_DEPLOYMENT,
        command_payload={
            "namespace": "staging",
            "target_revision": "v1.8.1",
        },
        execution_status=RemediationExecutionStatus.SUCCEEDED,
        started_at=now,
        completed_at=now,
        result_summary={
            "provider": "argocd",
            "accepted": True,
        },
    )
    db_session.add(execution)
    db_session.flush()

    verification = RecoveryVerification(
        remediation_id=context["recommendation"].id,
        remediation_execution_id=execution.id,
        verification_status=RecoveryVerificationStatus.VERIFIED,
        error_rate_recovered=True,
        latency_recovered=True,
        pods_healthy=True,
        restart_loop_absent=True,
        availability_restored=True,
        metrics_snapshot={
            "error_rate": 0.01,
            "latency_ms": 180,
            "available_replicas": 3,
            "desired_replicas": 3,
        },
        verified_at=now,
    )
    db_session.add(verification)
    db_session.commit()
    db_session.refresh(verification)

    assert verification.id is not None
    assert (
        verification.verification_status
        == RecoveryVerificationStatus.VERIFIED
    )
    assert verification.error_rate_recovered is True
    assert verification.latency_recovered is True
    assert verification.pods_healthy is True
    assert verification.restart_loop_absent is True
    assert verification.availability_restored is True
    assert verification.execution.id == execution.id
    assert (
        verification.remediation.id
        == context["recommendation"].id
    )


def test_terminal_verification_requires_verified_at(
    db_session,
):
    context = create_remediation_context(db_session)

    execution = RemediationExecution(
        remediation_id=context["recommendation"].id,
        command_type=ActionType.RESTART_POD,
        command_payload={
            "namespace": "staging",
            "pod_name": "payment-service-123",
        },
        execution_status=RemediationExecutionStatus.SUCCEEDED,
        result_summary={},
    )
    db_session.add(execution)
    db_session.flush()

    verification = RecoveryVerification(
        remediation_id=context["recommendation"].id,
        remediation_execution_id=execution.id,
        verification_status=RecoveryVerificationStatus.FAILED,
        metrics_snapshot={},
        verified_at=None,
    )
    db_session.add(verification)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_only_one_verification_is_allowed_per_execution(
    db_session,
):
    context = create_remediation_context(db_session)

    execution = RemediationExecution(
        remediation_id=context["recommendation"].id,
        command_type=ActionType.SCALE_REPLICAS,
        command_payload={
            "namespace": "staging",
            "replicas": 5,
        },
        execution_status=RemediationExecutionStatus.SUCCEEDED,
        result_summary={},
    )
    db_session.add(execution)
    db_session.flush()

    first_verification = RecoveryVerification(
        remediation_id=context["recommendation"].id,
        remediation_execution_id=execution.id,
        verification_status=RecoveryVerificationStatus.PENDING,
        metrics_snapshot={},
    )
    db_session.add(first_verification)
    db_session.flush()

    second_verification = RecoveryVerification(
        remediation_id=context["recommendation"].id,
        remediation_execution_id=execution.id,
        verification_status=RecoveryVerificationStatus.PENDING,
        metrics_snapshot={},
    )
    db_session.add(second_verification)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_incident_exposes_remediation_recommendations(
    db_session,
):
    context = create_remediation_context(db_session)

    incident_id = context["incident"].id
    recommendation_id = context["recommendation"].id

    db_session.commit()
    db_session.expire_all()

    incident = db_session.get(
        Incident,
        incident_id,
    )

    assert len(incident.remediation_recommendations) == 1
    assert (
        incident.remediation_recommendations[0].id
        == recommendation_id
    )


def test_service_exposes_remediation_recommendations(
    db_session,
):
    context = create_remediation_context(db_session)

    service_id = context["service"].id
    recommendation_id = context["recommendation"].id

    db_session.commit()
    db_session.expire_all()

    service = db_session.get(
        Service,
        service_id,
    )

    assert len(service.remediation_recommendations) == 1
    assert (
        service.remediation_recommendations[0].id
        == recommendation_id
    )