from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.events.constants import (
    REMEDIATION_COMMAND_CREATED,
    REMEDIATION_RECOMMENDED,
    TOPIC_REMEDIATION_EVENTS,
)
from app.models import (
    ActionType,
    AuditEvent,
    OutboxEvent,
    RCAConfidence,
    RecommendationStatus,
    RecoveryVerification,
    RemediationExecution,
)
from app.remediation import repository
from app.remediation import router as remediation_router
from app.remediation.events import (
    create_remediation_recommended_event,
)
from app.remediation.recommendation_service import (
    IncidentEvidenceMissingError,
    IncidentNotFoundError,
    NoSafeRemediationError,
    RCAReportMissingError,
    RecommendationInputsNotChangedError,
    RecommendationServiceResult,
)


BASE_TIME = datetime(
    2026,
    8,
    1,
    16,
    0,
    tzinfo=timezone.utc,
)


def auth_context(
    client: TestClient,
    *,
    role: str = "operator",
) -> tuple[dict[str, str], dict]:
    email = (
        f"remediation-{role}-{uuid4()}"
        "@example.com"
    )
    password = "RemediationTest123!"

    register_response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "role": role,
        },
    )

    assert register_response.status_code in {
        200,
        201,
    }, register_response.text

    token_payload = register_response.json()
    token = token_payload.get("access_token")

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

        token_payload = login_response.json()
        token = token_payload["access_token"]

    return (
        {
            "Authorization": f"Bearer {token}",
        },
        token_payload["user"],
    )


def make_recommendation(
    *,
    incident_id: UUID | None = None,
    created_by: str | None = None,
):
    incident_id = incident_id or uuid4()

    return SimpleNamespace(
        id=uuid4(),
        incident_id=incident_id,
        service_id="payment-service-id",
        environment="production",
        action_type=(
            ActionType.ROLLBACK_DEPLOYMENT
        ),
        reason=(
            "Service reliability regressed shortly "
            "after the latest deployment."
        ),
        evidence_summary={
            "rule_code": (
                "RECENT_DEPLOYMENT_REGRESSION"
            ),
            "incident_id": str(incident_id),
            "incident_evidence_id": str(uuid4()),
            "rca_report_id": str(uuid4()),
            "deployment_id": str(uuid4()),
            "deployment_revision": "v1.8.2",
            "deployed_minutes_before_incident": 2,
            "health_before": {
                "error_rate": 0.7,
                "latency_ms": 280,
            },
            "health_after": {
                "error_rate": 18.4,
                "latency_ms": 2300,
            },
            "matched_facts": [
                "APPLICATION_REGRESSION",
                "DEPLOYMENT_TEMPORAL_CORRELATION",
            ],
        },
        confidence=RCAConfidence.HIGH,
        status=(
            RecommendationStatus.PENDING_APPROVAL
        ),
        created_by=created_by,
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def test_created_recommendation_returns_201(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, current_user = auth_context(
        client,
        role="operator",
    )
    incident_id = uuid4()
    recommendation = make_recommendation(
        incident_id=incident_id,
        created_by=str(current_user["id"]),
    )

    def fake_recommend_remediation(
        *,
        db,
        incident_id: UUID,
        created_by: str | None,
    ):
        assert db is not None
        assert incident_id == recommendation.incident_id
        assert created_by == str(
            current_user["id"]
        )

        return RecommendationServiceResult(
            recommendation=recommendation,
            created=True,
        )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        fake_recommend_remediation,
    )

    response = client.post(
        (
            f"/api/incidents/{incident_id}"
            "/remediation/recommend"
        ),
        headers=headers,
    )

    assert response.status_code == 201, response.text

    body = response.json()

    assert body["id"] == str(recommendation.id)
    assert body["incident_id"] == str(incident_id)
    assert (
        body["action_type"]
        == "ROLLBACK_DEPLOYMENT"
    )
    assert body["confidence"] == "HIGH"
    assert body["status"] == "PENDING_APPROVAL"
    assert (
        body["evidence_summary"]["rule_code"]
        == "RECENT_DEPLOYMENT_REGRESSION"
    )
    assert (
        body["evidence_summary"][
            "incident_evidence_id"
        ]
        == recommendation.evidence_summary[
            "incident_evidence_id"
        ]
    )
    assert (
        body["evidence_summary"]["rca_report_id"]
        == recommendation.evidence_summary[
            "rca_report_id"
        ]
    )


def test_existing_active_recommendation_returns_200(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, current_user = auth_context(
        client,
        role="operator",
    )
    incident_id = uuid4()
    recommendation = make_recommendation(
        incident_id=incident_id,
        created_by=str(current_user["id"]),
    )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        lambda **_kwargs: (
            RecommendationServiceResult(
                recommendation=recommendation,
                created=False,
            )
        ),
    )

    first_response = client.post(
        (
            f"/api/incidents/{incident_id}"
            "/remediation/recommend"
        ),
        headers=headers,
    )
    second_response = client.post(
        (
            f"/api/incidents/{incident_id}"
            "/remediation/recommend"
        ),
        headers=headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert (
        first_response.json()["id"]
        == second_response.json()["id"]
        == str(recommendation.id)
    )


def test_unknown_incident_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = auth_context(client)

    def fake_service(**_kwargs):
        raise IncidentNotFoundError(
            "Incident not found"
        )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        fake_service,
    )

    response = client.post(
        (
            f"/api/incidents/{uuid4()}"
            "/remediation/recommend"
        ),
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "INCIDENT_NOT_FOUND",
        "message": "Incident not found",
    }


def test_missing_evidence_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = auth_context(client)

    def fake_service(**_kwargs):
        raise IncidentEvidenceMissingError(
            "Incident evidence is missing."
        )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        fake_service,
    )

    response = client.post(
        (
            f"/api/incidents/{uuid4()}"
            "/remediation/recommend"
        ),
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "INCIDENT_EVIDENCE_MISSING"
    )


def test_missing_rca_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = auth_context(client)

    def fake_service(**_kwargs):
        raise RCAReportMissingError(
            "RCA report is missing."
        )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        fake_service,
    )

    response = client.post(
        (
            f"/api/incidents/{uuid4()}"
            "/remediation/recommend"
        ),
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "RCA_REPORT_MISSING"
    )


def test_unchanged_inputs_return_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = auth_context(client)

    def fake_service(**_kwargs):
        raise RecommendationInputsNotChangedError(
            "A newer RCA report or incident evidence "
            "record is required before reevaluation."
        )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        fake_service,
    )

    response = client.post(
        (
            f"/api/incidents/{uuid4()}"
            "/remediation/recommend"
        ),
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "RECOMMENDATION_INPUTS_NOT_CHANGED"
    )


def test_no_safe_rule_returns_422_without_event(
    client: TestClient,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = auth_context(client)

    def fake_service(**_kwargs):
        raise NoSafeRemediationError(
            "Available evidence does not support "
            "a safe remediation."
        )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        fake_service,
    )

    response = client.post(
        (
            f"/api/incidents/{uuid4()}"
            "/remediation/recommend"
        ),
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "NO_SAFE_REMEDIATION",
        "message": (
            "Available evidence does not support "
            "a safe remediation."
        ),
    }

    assert (
        db_session.query(OutboxEvent).count()
        == 0
    )


def test_authentication_is_required(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_service_call(**_kwargs):
        pytest.fail(
            "Service must not run without authentication"
        )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        unexpected_service_call,
    )

    response = client.post(
        (
            f"/api/incidents/{uuid4()}"
            "/remediation/recommend"
        )
    )

    assert response.status_code == 401


def test_viewer_is_forbidden(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = auth_context(
        client,
        role="viewer",
    )

    def unexpected_service_call(**_kwargs):
        pytest.fail(
            "Viewer must be rejected before evaluation"
        )

    monkeypatch.setattr(
        remediation_router,
        "recommend_remediation",
        unexpected_service_call,
    )

    response = client.post(
        (
            f"/api/incidents/{uuid4()}"
            "/remediation/recommend"
        ),
        headers=headers,
    )

    assert response.status_code == 403

def test_recommended_event_is_advisory_only(
    db_session,
) -> None:
    recommendation = make_recommendation()

    create_remediation_recommended_event(
        db=db_session,
        recommendation=recommendation,
    )

    db_session.flush()

    events = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.correlation_id
            == str(recommendation.incident_id)
        )
        .all()
    )

    assert len(events) == 1

    event = events[0]

    assert (
        event.event_type
        == REMEDIATION_RECOMMENDED
    )
    assert event.topic == TOPIC_REMEDIATION_EVENTS
    assert event.status == "PENDING"
    assert event.payload["event_version"] == 1
    assert event.payload["occurred_at"] is not None
    assert (
        event.payload["rule_code"]
        == "RECENT_DEPLOYMENT_REGRESSION"
    )
    assert (
        event.payload["requires_human_approval"]
        is True
    )
    assert event.payload["advisory_only"] is True
    assert (
        event.payload["execution_requested"]
        is False
    )
    assert (
        event.payload["incident_evidence_id"]
        == recommendation.evidence_summary[
            "incident_evidence_id"
        ]
    )

    command_event_count = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type
            == REMEDIATION_COMMAND_CREATED
        )
        .count()
    )
    execution_count = (
        db_session.query(
            RemediationExecution,
        ).count()
    )
    recovery_verification_count = (
        db_session.query(
            RecoveryVerification,
        ).count()
    )

    assert command_event_count == 0
    assert execution_count == 0
    assert recovery_verification_count == 0

def test_recommendation_audit_event_is_created(
    db_session,
) -> None:
    recommendation = make_recommendation(
        created_by=None,
    )

    repository.create_recommendation_audit_event(
        db_session,
        recommendation=recommendation,
        requested_by=None,
    )

    db_session.flush()

    audit_event = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_id
            == str(recommendation.id)
        )
        .one()
    )

    assert (
        audit_event.action
        == "REMEDIATION_RECOMMENDED"
    )
    assert (
        audit_event.entity_type
        == "RemediationRecommendation"
    )

    details = json.loads(audit_event.details)

    assert details["actor_type"] == "SYSTEM"
    assert details["incident_id"] == str(
        recommendation.incident_id
    )
    assert (
        details["action_type"]
        == "ROLLBACK_DEPLOYMENT"
    )
    assert (
        details["rule_code"]
        == "RECENT_DEPLOYMENT_REGRESSION"
    )
    assert details["requires_approval"] is True