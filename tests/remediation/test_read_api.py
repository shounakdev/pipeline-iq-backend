from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.models import (
    AuditEvent,
    RecommendationStatus,
    RecoveryVerification,
    RecoveryVerificationStatus,
    RemediationExecution,
    RemediationRecommendation,
)
from app.remediation import repository
from tests.remediation.test_approval_workflow import (
    auth_context,
    create_pending_recommendation,
)


def add_recommendation_audit_event(
    db_session,
    *,
    recommendation: RemediationRecommendation,
    requested_by: str,
) -> None:
    repository.create_recommendation_audit_event(
        db_session,
        recommendation=recommendation,
        requested_by=requested_by,
    )

    db_session.commit()


@pytest.mark.parametrize(
    "role",
    [
        "admin",
        "operator",
        "developer",
        "viewer",
    ],
)
def test_all_read_roles_can_list_and_view_detail(
    client: TestClient,
    db_session,
    role: str,
) -> None:
    headers, current_user = auth_context(
        client,
        role=role,
    )

    _incident, recommendation = (
        create_pending_recommendation(
            db_session,
            created_by=str(current_user["id"]),
        )
    )

    remediation_id = recommendation.id

    add_recommendation_audit_event(
        db_session,
        recommendation=recommendation,
        requested_by=str(current_user["id"]),
    )

    status_before = recommendation.status

    execution_count_before = (
        db_session.query(RemediationExecution)
        .filter(
            RemediationExecution.remediation_id
            == remediation_id,
        )
        .count()
    )

    verification_count_before = (
        db_session.query(RecoveryVerification)
        .filter(
            RecoveryVerification.remediation_id
            == remediation_id,
        )
        .count()
    )

    list_response = client.get(
        "/api/remediations",
        headers=headers,
    )

    assert list_response.status_code == 200, (
        list_response.text
    )

    listed_remediation = next(
        (
            item
            for item in list_response.json()
            if item["id"] == str(remediation_id)
        ),
        None,
    )

    assert listed_remediation is not None
    assert (
        listed_remediation["status"]
        == "PENDING_APPROVAL"
    )
    assert listed_remediation["approval"] is None
    assert listed_remediation["execution"] is None
    assert listed_remediation["verification"] is None

    detail_response = client.get(
        (
            f"/api/remediations/"
            f"{remediation_id}/detail"
        ),
        headers=headers,
    )

    assert detail_response.status_code == 200, (
        detail_response.text
    )

    body = detail_response.json()

    assert body["id"] == str(remediation_id)
    assert (
        body["action_type"]
        == "ROLLBACK_DEPLOYMENT"
    )
    assert body["confidence"] == "HIGH"
    assert body["status"] == "PENDING_APPROVAL"
    assert body["approval"] is None
    assert body["execution"] is None
    assert body["verification"] is None

    assert len(body["audit_history"]) == 1

    audit_event = body["audit_history"][0]

    assert (
        audit_event["action"]
        == "REMEDIATION_RECOMMENDED"
    )
    assert (
        audit_event["entity_type"]
        == "RemediationRecommendation"
    )
    assert (
        audit_event["entity_id"]
        == str(remediation_id)
    )
    assert (
        audit_event["details"]["rule_code"]
        == "RECENT_DEPLOYMENT_REGRESSION"
    )

    db_session.expire_all()

    stored_recommendation = db_session.get(
        RemediationRecommendation,
        remediation_id,
    )

    assert stored_recommendation is not None
    assert stored_recommendation.status == status_before

    execution_count_after = (
        db_session.query(RemediationExecution)
        .filter(
            RemediationExecution.remediation_id
            == remediation_id,
        )
        .count()
    )

    verification_count_after = (
        db_session.query(RecoveryVerification)
        .filter(
            RecoveryVerification.remediation_id
            == remediation_id,
        )
        .count()
    )

    assert (
        execution_count_after
        == execution_count_before
    )
    assert (
        verification_count_after
        == verification_count_before
    )


def test_detail_includes_complete_workflow_state(
    client: TestClient,
    db_session,
) -> None:
    headers, current_user = auth_context(
        client,
        role="operator",
    )

    _incident, recommendation = (
        create_pending_recommendation(
            db_session,
            created_by=str(current_user["id"]),
        )
    )

    remediation_id = recommendation.id

    add_recommendation_audit_event(
        db_session,
        recommendation=recommendation,
        requested_by=str(current_user["id"]),
    )

    approval_response = client.post(
        (
            f"/api/remediations/"
            f"{remediation_id}/approve"
        ),
        headers=headers,
    )

    assert approval_response.status_code == 200, (
        approval_response.text
    )

    execution_response = client.post(
        (
            f"/api/remediations/"
            f"{remediation_id}/execute"
        ),
        headers=headers,
    )

    assert execution_response.status_code == 200, (
        execution_response.text
    )

    db_session.expire_all()

    stored_recommendation = db_session.get(
        RemediationRecommendation,
        remediation_id,
    )

    assert stored_recommendation is not None

    execution = (
        repository.get_execution_by_remediation_id(
            db_session,
            remediation_id,
        )
    )

    assert execution is not None

    repository.create_recovery_verification(
        db_session,
        remediation=stored_recommendation,
        execution=execution,
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
            "p95_latency_ms": 180.0,
            "available_replicas": 3,
            "replica_count": 3,
        },
        verified_at=datetime.now(timezone.utc),
    )

    db_session.commit()

    detail_response = client.get(
        (
            f"/api/remediations/"
            f"{remediation_id}/detail"
        ),
        headers=headers,
    )

    assert detail_response.status_code == 200, (
        detail_response.text
    )

    body = detail_response.json()

    assert body["status"] == "RECOVERY_VERIFIED"

    assert body["approval"] is not None
    assert (
        body["approval"]["decision"]
        == "APPROVED"
    )
    assert (
        body["approval"]["approved_by"]
        == str(current_user["id"])
    )

    assert body["execution"] is not None
    assert (
        body["execution"]["execution_status"]
        == "SUCCEEDED"
    )
    assert (
        body["execution"]["command_type"]
        == "ROLLBACK_DEPLOYMENT"
    )
    assert (
        body["execution"]["result_summary"][
            "command_type"
        ]
        == "ARGOCD_ROLLBACK"
    )
    assert (
        body["execution"]["result_summary"][
            "message"
        ]
        == "Rollback command accepted."
    )
    assert body["execution"]["completed_at"] is not None
    assert body["execution"]["error_message"] is None

    assert body["verification"] is not None
    assert (
        body["verification"][
            "verification_status"
        ]
        == "VERIFIED"
    )
    assert (
        body["verification"][
            "error_rate_recovered"
        ]
        is True
    )
    assert (
        body["verification"]["latency_recovered"]
        is True
    )
    assert (
        body["verification"]["pods_healthy"]
        is True
    )
    assert (
        body["verification"]["restart_loop_absent"]
        is True
    )
    assert (
        body["verification"][
            "availability_restored"
        ]
        is True
    )
    assert (
        body["verification"]["metrics_snapshot"][
            "p95_latency_ms"
        ]
        == 180.0
    )

    audit_actions = [
        event["action"]
        for event in body["audit_history"]
    ]

    assert audit_actions == [
        "REMEDIATION_RECOMMENDED",
        "REMEDIATION_APPROVED",
    ]


def test_detail_returns_not_found(
    client: TestClient,
) -> None:
    headers, _current_user = auth_context(
        client,
        role="viewer",
    )

    response = client.get(
        (
            f"/api/remediations/"
            f"{uuid4()}/detail"
        ),
        headers=headers,
    )

    assert response.status_code == 404
    assert (
        response.json()["detail"]["code"]
        == "REMEDIATION_NOT_FOUND"
    )


def test_read_endpoints_require_authentication(
    client: TestClient,
) -> None:
    list_response = client.get(
        "/api/remediations",
    )

    detail_response = client.get(
        (
            f"/api/remediations/"
            f"{uuid4()}/detail"
        ),
    )

    assert list_response.status_code in {
        401,
        403,
    }

    assert detail_response.status_code in {
        401,
        403,
    }
