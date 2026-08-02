from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.events.constants import (
    REMEDIATION_APPROVED,
    REMEDIATION_COMMAND_CREATED,
    REMEDIATION_REJECTED,
    TOPIC_REMEDIATION_EVENTS,
)
from app.models import (
    ActionType,
    ApprovalDecision,
    AuditEvent,
    Incident,
    OutboxEvent,
    Project,
    RCAConfidence,
    RecommendationStatus,
    RemediationApproval,
    RemediationExecution,
    RemediationRecommendation,
    Service,
)


def auth_context(
    client: TestClient,
    *,
    role: str,
) -> tuple[dict[str, str], dict]:
    email = (
        f"approval-{role}-{uuid4()}"
        "@example.com"
    )
    password = "RemediationTest123!"

    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "role": role,
        },
    )

    assert response.status_code in {
        200,
        201,
    }, response.text

    payload = response.json()
    token = payload.get("access_token")

    if token is None:
        login_response = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": password,
            },
        )

        assert login_response.status_code == 200, (
            login_response.text
        )

        payload = login_response.json()
        token = payload["access_token"]

    return (
        {
            "Authorization": f"Bearer {token}",
        },
        payload["user"],
    )


def create_pending_recommendation(
    db_session,
    *,
    created_by: str,
) -> tuple[Incident, RemediationRecommendation]:
    project = Project(
        id=str(uuid4()),
        name=f"Sprint 9C Project {uuid4()}",
        description=(
            "Project used by remediation approval tests."
        ),
        created_by=created_by,
    )
    db_session.add(project)
    db_session.flush()

    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name=f"payment-service-{uuid4()}",
        description=(
            "Service used by remediation approval tests."
        ),
        service_type="BACKEND",
        owner="platform-team",
    )
    db_session.add(service)
    db_session.flush()

    incident = Incident(
        title="Payment service reliability regression",
        description=(
            "Error rate increased after deployment."
        ),
        primary_service_id=service.id,
        environment="staging",
        created_by=created_by,
    )
    db_session.add(incident)
    db_session.flush()

    recommendation = RemediationRecommendation(
        incident_id=incident.id,
        service_id=service.id,
        environment="staging",
        action_type=(
            ActionType.ROLLBACK_DEPLOYMENT
        ),
        reason=(
            "A recent deployment is correlated with "
            "the reliability regression."
        ),
        evidence_summary={
            "rule_code": (
                "RECENT_DEPLOYMENT_REGRESSION"
            ),
            "deployment_revision": "v1.8.2",
            "previous_revision": "v1.8.1",
        },
        confidence=RCAConfidence.HIGH,
        created_by=created_by,
    )
    db_session.add(recommendation)
    db_session.commit()
    db_session.refresh(incident)
    db_session.refresh(recommendation)

    return incident, recommendation


@pytest.mark.parametrize(
    "role",
    [
        "admin",
        "operator",
    ],
)
def test_admin_and_sre_operator_can_approve(
    client: TestClient,
    db_session,
    role: str,
) -> None:
    headers, current_user = auth_context(
        client,
        role=role,
    )
    incident, recommendation = (
        create_pending_recommendation(
            db_session,
            created_by=str(current_user["id"]),
        )
    )

    response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/approve"
        ),
        headers=headers,
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["id"] == str(recommendation.id)
    assert body["incident_id"] == str(incident.id)
    assert body["status"] == "APPROVED"
    assert body["approval"] is not None
    assert (
        body["approval"]["decision"]
        == "APPROVED"
    )
    assert (
        body["approval"]["approved_by"]
        == str(current_user["id"])
    )
    assert (
        body["approval"]["rejection_reason"]
        is None
    )

    db_session.expire_all()

    stored = db_session.get(
        RemediationRecommendation,
        recommendation.id,
    )

    assert (
        stored.status
        == RecommendationStatus.APPROVED
    )

    approval = (
        db_session.query(RemediationApproval)
        .filter(
            RemediationApproval.remediation_id
            == recommendation.id,
        )
        .one()
    )

    assert (
        approval.decision
        == ApprovalDecision.APPROVED
    )

    audit_event = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_id
            == str(recommendation.id),
            AuditEvent.action
            == REMEDIATION_APPROVED,
        )
        .one()
    )

    audit_details = json.loads(
        audit_event.details,
    )

    assert (
        audit_event.actor_id
        == str(current_user["id"])
    )
    assert (
        audit_details["decision"]
        == "APPROVED"
    )
    assert (
        audit_details["new_status"]
        == "APPROVED"
    )

    outbox_event = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type
            == REMEDIATION_APPROVED,
            OutboxEvent.correlation_id
            == str(incident.id),
        )
        .one()
    )

    assert (
        outbox_event.topic
        == TOPIC_REMEDIATION_EVENTS
    )
    assert outbox_event.status == "PENDING"
    assert (
        outbox_event.payload["decision"]
        == "APPROVED"
    )
    assert (
        outbox_event.payload[
            "execution_requested"
        ]
        is False
    )


@pytest.mark.parametrize(
    "role",
    [
        "developer",
        "viewer",
    ],
)
def test_developer_and_viewer_cannot_approve(
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

    response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/approve"
        ),
        headers=headers,
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "Insufficient permissions"
    )

    db_session.expire_all()

    stored = db_session.get(
        RemediationRecommendation,
        recommendation.id,
    )

    assert (
        stored.status
        == RecommendationStatus.PENDING_APPROVAL
    )

    assert (
        db_session.query(RemediationApproval)
        .filter(
            RemediationApproval.remediation_id
            == recommendation.id,
        )
        .count()
        == 0
    )

    assert (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_id
            == str(recommendation.id),
        )
        .count()
        == 0
    )


def test_rejected_remediation_performs_no_action(
    client: TestClient,
    db_session,
) -> None:
    headers, current_user = auth_context(
        client,
        role="operator",
    )
    incident, recommendation = (
        create_pending_recommendation(
            db_session,
            created_by=str(current_user["id"]),
        )
    )

    rejection_reason = (
        "Rollback evidence is not sufficient."
    )

    response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/reject"
        ),
        headers=headers,
        json={
            "rejection_reason": rejection_reason,
        },
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["status"] == "REJECTED"
    assert (
        body["approval"]["decision"]
        == "REJECTED"
    )
    assert (
        body["approval"]["rejection_reason"]
        == rejection_reason
    )

    db_session.expire_all()

    stored = db_session.get(
        RemediationRecommendation,
        recommendation.id,
    )

    assert (
        stored.status
        == RecommendationStatus.REJECTED
    )

    approval = (
        db_session.query(RemediationApproval)
        .filter(
            RemediationApproval.remediation_id
            == recommendation.id,
        )
        .one()
    )

    assert (
        approval.decision
        == ApprovalDecision.REJECTED
    )
    assert (
        approval.rejection_reason
        == rejection_reason
    )

    assert (
        db_session.query(RemediationExecution)
        .filter(
            RemediationExecution.remediation_id
            == recommendation.id,
        )
        .count()
        == 0
    )

    assert (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type
            == REMEDIATION_COMMAND_CREATED,
            OutboxEvent.correlation_id
            == str(incident.id),
        )
        .count()
        == 0
    )

    rejected_event = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type
            == REMEDIATION_REJECTED,
            OutboxEvent.correlation_id
            == str(incident.id),
        )
        .one()
    )

    assert (
        rejected_event.topic
        == TOPIC_REMEDIATION_EVENTS
    )
    assert (
        rejected_event.payload["decision"]
        == "REJECTED"
    )
    assert (
        rejected_event.payload[
            "execution_requested"
        ]
        is False
    )

    audit_event = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_id
            == str(recommendation.id),
            AuditEvent.action
            == REMEDIATION_REJECTED,
        )
        .one()
    )

    details = json.loads(audit_event.details)

    assert details["decision"] == "REJECTED"
    assert (
        details["rejection_reason"]
        == rejection_reason
    )


def test_remediation_cannot_be_decided_twice(
    client: TestClient,
    db_session,
) -> None:
    headers, current_user = auth_context(
        client,
        role="admin",
    )
    _incident, recommendation = (
        create_pending_recommendation(
            db_session,
            created_by=str(current_user["id"]),
        )
    )

    approve_response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/approve"
        ),
        headers=headers,
    )

    assert approve_response.status_code == 200

    reject_response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/reject"
        ),
        headers=headers,
        json={
            "rejection_reason": (
                "Attempted second decision."
            ),
        },
    )

    assert reject_response.status_code == 409
    assert (
        reject_response.json()["detail"]["code"]
        == "REMEDIATION_ALREADY_DECIDED"
    )

    db_session.expire_all()

    assert (
        db_session.query(RemediationApproval)
        .filter(
            RemediationApproval.remediation_id
            == recommendation.id,
        )
        .count()
        == 1
    )


def test_list_and_status_endpoints(
    client: TestClient,
    db_session,
) -> None:
    headers, current_user = auth_context(
        client,
        role="viewer",
    )
    incident, recommendation = (
        create_pending_recommendation(
            db_session,
            created_by=str(current_user["id"]),
        )
    )

    list_response = client.get(
        (
            f"/api/incidents/{incident.id}"
            "/remediations"
        ),
        headers=headers,
    )

    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert (
        list_response.json()[0]["id"]
        == str(recommendation.id)
    )
    assert (
        list_response.json()[0]["status"]
        == "PENDING_APPROVAL"
    )

    status_response = client.get(
        (
            f"/api/remediations/"
            f"{recommendation.id}/status"
        ),
        headers=headers,
    )

    assert status_response.status_code == 200

    body = status_response.json()

    assert body["id"] == str(recommendation.id)
    assert body["status"] == "PENDING_APPROVAL"
    assert body["approval"] is None
