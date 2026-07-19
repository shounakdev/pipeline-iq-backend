from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.incidents import incident_router
from app.incidents.enums import IncidentSeverity, IncidentStatus
from app.incidents.schemas import (
    IncidentAssignmentResponse,
    IncidentCommentResponse,
    IncidentDetailResponse,
    IncidentListItemResponse,
    IncidentListResponse,
    IncidentMetricResponse,
    IncidentMetricsResponse,
    IncidentTimelineEventResponse,
    IncidentTimelineResponse,
    OperatorSummaryResponse,
    ServiceSummaryResponse,
)
from app.incidents.service import (
    IncidentConflictError,
    IncidentNotFoundError,
)


BASE_TIME = datetime(
    2026,
    7,
    19,
    10,
    0,
    tzinfo=timezone.utc,
)


def _auth_context(
    client: TestClient,
    *,
    role: str = "developer",
) -> tuple[dict[str, str], dict]:
    email = f"{role}-{uuid4()}@example.com"
    password = "IncidentTest123!"

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

    headers = {
        "Authorization": f"Bearer {token}",
    }

    return headers, token_payload["user"]


def _operator(
    user_id: str = "operator-1",
) -> OperatorSummaryResponse:
    return OperatorSummaryResponse(
        id=user_id,
        email=f"{user_id}@example.com",
        full_name="Incident Operator",
    )


def _incident_item(
    *,
    incident_id: UUID | None = None,
    status: IncidentStatus = IncidentStatus.DETECTED,
    severity: IncidentSeverity = IncidentSeverity.SEV_2,
    service_id: str = "service-api",
    environment: str = "production",
    assigned_operator: OperatorSummaryResponse | None = None,
    detected_at: datetime = BASE_TIME,
    acknowledged_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> IncidentListItemResponse:
    incident_id = incident_id or uuid4()

    return IncidentListItemResponse(
        incident_id=incident_id,
        id=incident_id,
        incident_number="INC-001",
        title="Payment API latency incident",
        severity=severity,
        status=status,
        service_id=service_id,
        service_name="payment-service",
        environment=environment,
        assigned_operator=assigned_operator,
        failure_started_at=(
            detected_at - timedelta(minutes=5)
        ),
        detected_at=detected_at,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
        created_at=detected_at,
        updated_at=resolved_at or acknowledged_at or detected_at,
    )


def _assignment(
    *,
    incident_id: UUID,
    assigned_to_user_id: str,
    assigned_by_user_id: str | None = None,
) -> IncidentAssignmentResponse:
    return IncidentAssignmentResponse(
        id=uuid4(),
        incident_id=incident_id,
        assigned_to_user_id=assigned_to_user_id,
        assigned_to_user=_operator(
            assigned_to_user_id,
        ),
        assigned_by_user_id=assigned_by_user_id,
        assigned_by_user=(
            _operator(assigned_by_user_id)
            if assigned_by_user_id
            else None
        ),
        assignment_note="Assigned through API test",
        assigned_at=BASE_TIME,
        unassigned_at=None,
        is_active=True,
    )


def _detail(
    *,
    item: IncidentListItemResponse | None = None,
    current_assignment: IncidentAssignmentResponse | None = None,
    comments: list[IncidentCommentResponse] | None = None,
    timeline_events: list[
        IncidentTimelineEventResponse
    ] | None = None,
) -> IncidentDetailResponse:
    item = item or _incident_item()

    return IncidentDetailResponse(
        incident=item,
        description="Latency exceeded the configured SLO.",
        deduplication_key=(
            f"{item.service_id}:{item.environment}:p95-latency"
        ),
        primary_service=ServiceSummaryResponse(
            id=item.service_id,
            name=item.service_name or "payment-service",
            service_type="backend",
            owner="platform-team",
        ),
        affected_services=[
            ServiceSummaryResponse(
                id=item.service_id,
                name=item.service_name or "payment-service",
                service_type="backend",
                owner="platform-team",
            )
        ],
        current_assignment=current_assignment,
        assignment_history=(
            [current_assignment]
            if current_assignment is not None
            else []
        ),
        comments=comments or [],
        timeline_summary=timeline_events or [],
    )


def _timeline_event(
    *,
    incident_id: UUID,
    event_id: UUID,
    occurred_at: datetime,
    event_type: str,
) -> IncidentTimelineEventResponse:
    return IncidentTimelineEventResponse(
        id=event_id,
        incident_id=incident_id,
        event_type=event_type,
        source="SYSTEM",
        message=event_type.replace("_", " ").title(),
        metadata_json={},
        occurred_at=occurred_at,
        created_at=occurred_at,
    )


def _paginated_response(
    *items: IncidentListItemResponse,
    page: int = 1,
    page_size: int = 25,
    total: int | None = None,
) -> IncidentListResponse:
    return IncidentListResponse.create(
        items=list(items),
        total=len(items) if total is None else total,
        page=page,
        page_size=page_size,
    )


def test_list_incidents_returns_paginated_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    first = _incident_item()
    second = _incident_item(
        incident_id=uuid4(),
        severity=IncidentSeverity.SEV_3,
    )

    def fake_list_incidents(
        _db,
        **kwargs,
    ) -> IncidentListResponse:
        assert kwargs["page"] == 2
        assert kwargs["page_size"] == 2

        return _paginated_response(
            first,
            second,
            page=2,
            page_size=2,
            total=5,
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        fake_list_incidents,
    )

    response = client.get(
        "/api/incidents",
        params={
            "page": 2,
            "page_size": 2,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert len(body["items"]) == 2
    assert body["total"] == 5
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["total_pages"] == 3


def test_list_incidents_filters_by_status(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def fake_list_incidents(
        _db,
        **kwargs,
    ) -> IncidentListResponse:
        assert kwargs["status"] == (
            IncidentStatus.ACKNOWLEDGED
        )

        return _paginated_response(
            _incident_item(
                status=IncidentStatus.ACKNOWLEDGED,
                acknowledged_at=BASE_TIME,
            )
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        fake_list_incidents,
    )

    response = client.get(
        "/api/incidents",
        params={"status": "ACKNOWLEDGED"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert all(
        item["status"] == "ACKNOWLEDGED"
        for item in response.json()["items"]
    )


def test_list_incidents_filters_by_severity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def fake_list_incidents(
        _db,
        **kwargs,
    ) -> IncidentListResponse:
        assert kwargs["severity"] == (
            IncidentSeverity.SEV_1
        )

        return _paginated_response(
            _incident_item(
                severity=IncidentSeverity.SEV_1,
            )
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        fake_list_incidents,
    )

    response = client.get(
        "/api/incidents",
        params={"severity": "SEV-1"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert all(
        item["severity"] == "SEV-1"
        for item in response.json()["items"]
    )


def test_list_incidents_filters_by_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)
    service_id = "payment-service-id"

    def fake_list_incidents(
        _db,
        **kwargs,
    ) -> IncidentListResponse:
        assert kwargs["service_id"] == service_id

        return _paginated_response(
            _incident_item(
                service_id=service_id,
            )
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        fake_list_incidents,
    )

    response = client.get(
        "/api/incidents",
        params={"service_id": service_id},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert all(
        item["service_id"] == service_id
        for item in response.json()["items"]
    )


def test_list_incidents_filters_by_environment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def fake_list_incidents(
        _db,
        **kwargs,
    ) -> IncidentListResponse:
        assert kwargs["environment"] == "staging"

        return _paginated_response(
            _incident_item(
                environment="staging",
            )
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        fake_list_incidents,
    )

    response = client.get(
        "/api/incidents",
        params={"environment": "staging"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert all(
        item["environment"] == "staging"
        for item in response.json()["items"]
    )


def test_list_incidents_filters_by_assignee(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)
    assignee_id = "operator-42"

    def fake_list_incidents(
        _db,
        **kwargs,
    ) -> IncidentListResponse:
        assert kwargs["assignee_id"] == assignee_id

        return _paginated_response(
            _incident_item(
                assigned_operator=_operator(
                    assignee_id,
                ),
            )
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        fake_list_incidents,
    )

    response = client.get(
        "/api/incidents",
        params={"assignee_id": assignee_id},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert all(
        item["assigned_operator"]["id"]
        == assignee_id
        for item in response.json()["items"]
    )


def test_list_incidents_filters_by_date_range(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)
    from_date = BASE_TIME - timedelta(hours=1)
    to_date = BASE_TIME + timedelta(hours=1)

    def fake_list_incidents(
        _db,
        **kwargs,
    ) -> IncidentListResponse:
        assert kwargs["from_date"] == from_date
        assert kwargs["to_date"] == to_date

        return _paginated_response(
            _incident_item(
                detected_at=BASE_TIME,
            )
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        fake_list_incidents,
    )

    response = client.get(
        "/api/incidents",
        params={
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1


def test_list_incidents_rejects_invalid_page(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def unexpected_service_call(*_args, **_kwargs):
        pytest.fail(
            "Service must not run when page validation fails"
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        unexpected_service_call,
    )

    response = client.get(
        "/api/incidents",
        params={"page": 0},
        headers=headers,
    )

    assert response.status_code == 422


def test_list_incidents_rejects_invalid_date_range(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def unexpected_service_call(*_args, **_kwargs):
        pytest.fail(
            "Service must not run when date validation fails"
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "list_incidents",
        unexpected_service_call,
    )

    response = client.get(
        "/api/incidents",
        params={
            "from_date": (
                BASE_TIME + timedelta(days=1)
            ).isoformat(),
            "to_date": BASE_TIME.isoformat(),
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "from_date cannot be later than to_date"
    )


def test_get_incident_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)
    incident_id = uuid4()
    detail = _detail(
        item=_incident_item(
            incident_id=incident_id,
        )
    )

    def fake_get_incident_detail(
        _db,
        *,
        incident_id: UUID,
    ) -> IncidentDetailResponse:
        assert incident_id == detail.incident.incident_id
        return detail

    monkeypatch.setattr(
        incident_router.incident_service,
        "get_incident_detail",
        fake_get_incident_detail,
    )

    response = client.get(
        f"/api/incidents/{incident_id}",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["incident"]["incident_id"] == (
        str(incident_id)
    )
    assert response.json()["primary_service"]["id"] == (
        "service-api"
    )


def test_get_missing_incident_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def fake_get_incident_detail(*_args, **_kwargs):
        raise IncidentNotFoundError(
            "Incident not found"
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "get_incident_detail",
        fake_get_incident_detail,
    )

    response = client.get(
        f"/api/incidents/{uuid4()}",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Incident not found",
    }


def test_acknowledge_incident(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, current_user = _auth_context(client)
    incident_id = uuid4()

    def fake_acknowledge_incident(
        _db,
        *,
        incident_id: UUID,
        request,
        actor_user_id: str,
    ) -> IncidentDetailResponse:
        assert incident_id == expected_incident_id
        assert request.note == "Taking ownership"
        assert request.assign_to_self is False
        assert actor_user_id == str(
            current_user["id"]
        )

        return _detail(
            item=_incident_item(
                incident_id=incident_id,
                status=IncidentStatus.ACKNOWLEDGED,
                acknowledged_at=BASE_TIME,
            )
        )

    expected_incident_id = incident_id

    monkeypatch.setattr(
        incident_router.incident_service,
        "acknowledge_incident",
        fake_acknowledge_incident,
    )

    response = client.post(
        f"/api/incidents/{incident_id}/acknowledge",
        json={
            "note": "Taking ownership",
            "assign_to_self": False,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["incident"]["status"] == (
        "ACKNOWLEDGED"
    )
    assert (
        response.json()["incident"]["acknowledged_at"]
        is not None
    )


def test_acknowledge_incident_assigns_to_self(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, current_user = _auth_context(client)
    incident_id = uuid4()
    actor_user_id = str(current_user["id"])

    def fake_acknowledge_incident(
        _db,
        *,
        incident_id: UUID,
        request,
        actor_user_id: str,
    ) -> IncidentDetailResponse:
        assert request.assign_to_self is True

        assignment = _assignment(
            incident_id=incident_id,
            assigned_to_user_id=actor_user_id,
            assigned_by_user_id=actor_user_id,
        )

        return _detail(
            item=_incident_item(
                incident_id=incident_id,
                status=IncidentStatus.ACKNOWLEDGED,
                assigned_operator=_operator(
                    actor_user_id,
                ),
                acknowledged_at=BASE_TIME,
            ),
            current_assignment=assignment,
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "acknowledge_incident",
        fake_acknowledge_incident,
    )

    response = client.post(
        f"/api/incidents/{incident_id}/acknowledge",
        json={
            "note": "I will investigate",
            "assign_to_self": True,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert (
        response.json()["current_assignment"][
            "assigned_to_user_id"
        ]
        == actor_user_id
    )


def test_acknowledge_already_acknowledged_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def fake_acknowledge_incident(*_args, **_kwargs):
        raise IncidentConflictError(
            "Incident is already acknowledged"
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "acknowledge_incident",
        fake_acknowledge_incident,
    )

    response = client.post(
        f"/api/incidents/{uuid4()}/acknowledge",
        json={
            "note": "Duplicate acknowledgement",
            "assign_to_self": False,
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Incident is already acknowledged"
    )


def test_assign_incident(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, current_user = _auth_context(client)
    incident_id = uuid4()
    assignee_id = "target-operator"

    def fake_assign_incident(
        _db,
        *,
        incident_id: UUID,
        request,
        assigned_by_user_id: str,
    ) -> IncidentDetailResponse:
        assert incident_id == expected_incident_id
        assert request.assigned_to_user_id == (
            assignee_id
        )
        assert request.note == "Primary responder"
        assert assigned_by_user_id == str(
            current_user["id"]
        )

        assignment = _assignment(
            incident_id=incident_id,
            assigned_to_user_id=assignee_id,
            assigned_by_user_id=assigned_by_user_id,
        )

        return _detail(
            item=_incident_item(
                incident_id=incident_id,
                assigned_operator=_operator(
                    assignee_id,
                ),
            ),
            current_assignment=assignment,
        )

    expected_incident_id = incident_id

    monkeypatch.setattr(
        incident_router.incident_service,
        "assign_incident",
        fake_assign_incident,
    )

    response = client.post(
        f"/api/incidents/{incident_id}/assign",
        json={
            "assigned_to_user_id": assignee_id,
            "note": "Primary responder",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert (
        response.json()["current_assignment"][
            "assigned_to_user_id"
        ]
        == assignee_id
    )


def test_assign_current_assignee_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def fake_assign_incident(*_args, **_kwargs):
        raise IncidentConflictError(
            "User is already the current assignee"
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "assign_incident",
        fake_assign_incident,
    )

    response = client.post(
        f"/api/incidents/{uuid4()}/assign",
        json={
            "assigned_to_user_id": "operator-1",
            "note": "Duplicate assignment",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "User is already the current assignee"
    )


def test_change_incident_status(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, current_user = _auth_context(client)
    incident_id = uuid4()

    def fake_update_incident_status(
        _db,
        *,
        incident_id: UUID,
        request,
        actor_user_id: str,
    ) -> IncidentDetailResponse:
        assert incident_id == expected_incident_id
        assert request.status == (
            IncidentStatus.INVESTIGATING
        )
        assert request.reason == (
            "Reviewing traces and deployment history"
        )
        assert actor_user_id == str(
            current_user["id"]
        )

        return _detail(
            item=_incident_item(
                incident_id=incident_id,
                status=IncidentStatus.INVESTIGATING,
                acknowledged_at=BASE_TIME,
            )
        )

    expected_incident_id = incident_id

    monkeypatch.setattr(
        incident_router.incident_service,
        "update_incident_status",
        fake_update_incident_status,
    )

    response = client.post(
        f"/api/incidents/{incident_id}/status",
        json={
            "status": "INVESTIGATING",
            "reason": (
                "Reviewing traces and deployment history"
            ),
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["incident"]["status"] == (
        "INVESTIGATING"
    )


def test_invalid_status_transition_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def fake_update_incident_status(*_args, **_kwargs):
        raise IncidentConflictError(
            "Invalid incident status transition: "
            "DETECTED -> RESOLVED"
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "update_incident_status",
        fake_update_incident_status,
    )

    response = client.post(
        f"/api/incidents/{uuid4()}/status",
        json={
            "status": "RESOLVED",
            "reason": "Attempt invalid direct resolution",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "Invalid incident status transition: "
            "DETECTED -> RESOLVED"
        )
    }


def test_resolve_incident_sets_resolved_at(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)
    incident_id = uuid4()
    resolved_at = BASE_TIME + timedelta(minutes=30)

    def fake_update_incident_status(
        _db,
        *,
        incident_id: UUID,
        request,
        actor_user_id: str,
    ) -> IncidentDetailResponse:
        assert request.status == IncidentStatus.RESOLVED
        assert actor_user_id

        return _detail(
            item=_incident_item(
                incident_id=incident_id,
                status=IncidentStatus.RESOLVED,
                acknowledged_at=BASE_TIME,
                resolved_at=resolved_at,
            )
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "update_incident_status",
        fake_update_incident_status,
    )

    response = client.post(
        f"/api/incidents/{incident_id}/status",
        json={
            "status": "RESOLVED",
            "reason": "Rollback restored service health",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text

    returned_resolved_at = (
        response.json()["incident"]["resolved_at"]
    )

    assert returned_resolved_at is not None
    assert datetime.fromisoformat(
        returned_resolved_at.replace(
            "Z",
            "+00:00",
        )
    ) == resolved_at


def test_add_comment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, current_user = _auth_context(client)
    incident_id = uuid4()

    def fake_add_incident_comment(
        _db,
        *,
        incident_id: UUID,
        request,
        actor,
    ) -> IncidentCommentResponse:
        assert incident_id == expected_incident_id
        assert request.comment == (
            "Rollback completed successfully."
        )
        assert str(actor.id) == str(
            current_user["id"]
        )

        return IncidentCommentResponse(
            id=uuid4(),
            incident_id=incident_id,
            author_user_id=str(actor.id),
            author=_operator(str(actor.id)),
            comment=request.comment,
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )

    expected_incident_id = incident_id

    monkeypatch.setattr(
        incident_router.incident_service,
        "add_incident_comment",
        fake_add_incident_comment,
    )

    response = client.post(
        f"/api/incidents/{incident_id}/comments",
        json={
            "comment": (
                "Rollback completed successfully."
            )
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["comment"] == (
        "Rollback completed successfully."
    )
    assert response.json()["incident_id"] == (
        str(incident_id)
    )


def test_blank_comment_returns_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)

    def unexpected_service_call(*_args, **_kwargs):
        pytest.fail(
            "Service must not run when comment validation fails"
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "add_incident_comment",
        unexpected_service_call,
    )

    response = client.post(
        f"/api/incidents/{uuid4()}/comments",
        json={"comment": "   "},
        headers=headers,
    )

    assert response.status_code == 422


def test_timeline_is_chronological(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)
    incident_id = uuid4()

    first_id = UUID(
        "00000000-0000-0000-0000-000000000001"
    )
    second_id = UUID(
        "00000000-0000-0000-0000-000000000002"
    )
    third_id = UUID(
        "00000000-0000-0000-0000-000000000003"
    )

    events = [
        _timeline_event(
            incident_id=incident_id,
            event_id=first_id,
            occurred_at=BASE_TIME,
            event_type="INCIDENT_CREATED",
        ),
        _timeline_event(
            incident_id=incident_id,
            event_id=second_id,
            occurred_at=BASE_TIME + timedelta(minutes=5),
            event_type="INCIDENT_ACKNOWLEDGED",
        ),
        _timeline_event(
            incident_id=incident_id,
            event_id=third_id,
            occurred_at=BASE_TIME + timedelta(minutes=5),
            event_type="OPERATOR_ASSIGNED",
        ),
    ]

    def fake_get_incident_timeline(
        _db,
        *,
        incident_id: UUID,
    ) -> IncidentTimelineResponse:
        return IncidentTimelineResponse(
            incident_id=incident_id,
            events=events,
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "get_incident_timeline",
        fake_get_incident_timeline,
    )

    response = client.get(
        f"/api/incidents/{incident_id}/timeline",
        headers=headers,
    )

    assert response.status_code == 200, response.text

    events = response.json()["events"]

    ordering = [
        (
            event["occurred_at"],
            event["id"],
        )
        for event in events
    ]

    assert ordering == sorted(ordering)


def test_incident_metrics_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_context(client)
    incident_id = uuid4()

    metric = IncidentMetricResponse(
        id=uuid4(),
        incident_id=incident_id,
        metric_type="SLO_MEASUREMENT",
        metric_name="P95_LATENCY",
        value=2300.0,
        unit="ms",
        source="PROMETHEUS",
        captured_at=BASE_TIME,
        metadata_json={
            "snapshot_reason": "incident_detection",
        },
        created_at=BASE_TIME,
    )

    def fake_get_incident_metrics(
        _db,
        *,
        incident_id: UUID,
    ) -> IncidentMetricsResponse:
        return IncidentMetricsResponse(
            incident_id=incident_id,
            metric_snapshot=[metric],
            mttd_seconds=300,
            mtta_seconds=120,
            mttr_seconds=1800,
            mttd_display="5m",
            mtta_display="2m",
            mttr_display="30m",
            alert_threshold=2000.0,
            triggered_value=2300.0,
            error_budget_status="EXHAUSTED",
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "get_incident_metrics",
        fake_get_incident_metrics,
    )

    response = client.get(
        f"/api/incidents/{incident_id}/metrics",
        headers=headers,
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["incident_id"] == str(incident_id)
    assert body["mttd_seconds"] == 300
    assert body["mtta_seconds"] == 120
    assert body["mttr_seconds"] == 1800
    assert body["metric_snapshot"][0]["metric_name"] == (
        "P95_LATENCY"
    )


def test_read_role_is_required(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/incidents",
    )

    assert response.status_code == 401


def test_modify_role_is_required(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer_headers, _ = _auth_context(
        client,
        role="viewer",
    )

    def unexpected_service_call(*_args, **_kwargs):
        pytest.fail(
            "Viewer must be rejected before service execution"
        )

    monkeypatch.setattr(
        incident_router.incident_service,
        "add_incident_comment",
        unexpected_service_call,
    )

    response = client.post(
        f"/api/incidents/{uuid4()}/comments",
        json={
            "comment": "Viewer must not modify incidents."
        },
        headers=viewer_headers,
    )

    assert response.status_code == 403