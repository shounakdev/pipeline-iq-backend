from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.events.constants import (
    ROLLBACK_COMPLETED,
    ROLLBACK_STARTED,
    TOPIC_REMEDIATION_COMMANDS,
    TOPIC_REMEDIATION_RESULTS,
)
from app.models import (
    OutboxEvent,
    RecommendationStatus,
    RemediationExecution,
    RemediationExecutionStatus,
)
from tests.remediation.test_approval_workflow import (
    auth_context,
    create_pending_recommendation,
)


@pytest.mark.parametrize(
    "role",
    [
        "admin",
        "operator",
    ],
)
def test_admin_and_operator_can_execute_remediation(
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

    approval_response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/approve"
        ),
        headers=headers,
    )

    assert approval_response.status_code == 200, (
        approval_response.text
    )

    response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/execute"
        ),
        headers=headers,
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert (
        body["remediation_id"]
        == str(recommendation.id)
    )
    assert (
        body["action_type"]
        == "ROLLBACK_DEPLOYMENT"
    )
    assert (
        body["command_type"]
        == "ARGOCD_ROLLBACK"
    )
    assert body["status"] == "COMPLETED"
    assert (
        body["message"]
        == "Rollback command accepted."
    )
    assert body["target_revision"] == "v1.8.1"
    assert body["simulated"] is True
    assert body["started_at"] is not None
    assert body["completed_at"] is not None

    db_session.expire_all()

    stored_execution = (
        db_session.query(RemediationExecution)
        .filter(
            RemediationExecution.remediation_id
            == recommendation.id,
        )
        .one()
    )

    assert (
        stored_execution.execution_status
        == RemediationExecutionStatus.SUCCEEDED
    )
    assert (
        stored_execution.result_summary[
            "command_type"
        ]
        == "ARGOCD_ROLLBACK"
    )

    stored_recommendation = (
        db_session.get(
            type(recommendation),
            recommendation.id,
        )
    )

    assert (
        stored_recommendation.status
        == RecommendationStatus.COMPLETED
    )

    rollback_events = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.correlation_id
            == str(recommendation.incident_id),
            OutboxEvent.event_type.in_(
                [
                    ROLLBACK_STARTED,
                    ROLLBACK_COMPLETED,
                ]
            ),
        )
        .all()
    )

    events_by_type = {
        event.event_type: event
        for event in rollback_events
    }

    assert set(events_by_type) == {
        ROLLBACK_STARTED,
        ROLLBACK_COMPLETED,
    }
    assert (
        events_by_type[ROLLBACK_STARTED].topic
        == TOPIC_REMEDIATION_COMMANDS
    )
    assert (
        events_by_type[ROLLBACK_COMPLETED].topic
        == TOPIC_REMEDIATION_RESULTS
    )


@pytest.mark.parametrize(
    "role",
    [
        "developer",
        "viewer",
    ],
)
def test_developer_and_viewer_cannot_execute(
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
            f"{recommendation.id}/execute"
        ),
        headers=headers,
    )

    assert response.status_code == 403

    execution_count = (
        db_session.query(RemediationExecution)
        .filter(
            RemediationExecution.remediation_id
            == recommendation.id,
        )
        .count()
    )

    assert execution_count == 0


def test_rejected_remediation_cannot_execute(
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

    rejection_response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/reject"
        ),
        headers=headers,
        json={
            "rejection_reason": (
                "Rollback risk is too high."
            ),
        },
    )

    assert rejection_response.status_code == 200, (
        rejection_response.text
    )

    response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/execute"
        ),
        headers=headers,
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]["code"]
        == "REMEDIATION_EXECUTION_BLOCKED"
    )

    execution_count = (
        db_session.query(RemediationExecution)
        .filter(
            RemediationExecution.remediation_id
            == recommendation.id,
        )
        .count()
    )

    assert execution_count == 0


def test_execution_requires_prior_approval(
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

    response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/execute"
        ),
        headers=headers,
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]["code"]
        == "REMEDIATION_EXECUTION_BLOCKED"
    )


def test_duplicate_execution_returns_conflict(
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

    approval_response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/approve"
        ),
        headers=headers,
    )

    assert approval_response.status_code == 200

    first_response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/execute"
        ),
        headers=headers,
    )

    assert first_response.status_code == 200

    second_response = client.post(
        (
            f"/api/remediations/"
            f"{recommendation.id}/execute"
        ),
        headers=headers,
    )

    assert second_response.status_code == 409
    assert (
        second_response.json()["detail"]["code"]
        == "REMEDIATION_EXECUTION_BLOCKED"
    )

    execution_count = (
        db_session.query(RemediationExecution)
        .filter(
            RemediationExecution.remediation_id
            == recommendation.id,
        )
        .count()
    )

    assert execution_count == 1


def test_unknown_remediation_returns_not_found(
    client: TestClient,
) -> None:
    headers, _current_user = auth_context(
        client,
        role="admin",
    )

    response = client.post(
        f"/api/remediations/{uuid4()}/execute",
        headers=headers,
    )

    assert response.status_code == 404
    assert (
        response.json()["detail"]["code"]
        == "REMEDIATION_NOT_FOUND"
    )
