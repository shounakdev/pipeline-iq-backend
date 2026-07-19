import json

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from fastapi import HTTPException
from pydantic import ValidationError

from app.auth.dependencies import require_roles
from app.incidents import service
from app.incidents.incident_router import (
    _raise_incident_error,
)
from app.incidents.schemas import (
    IncidentAcknowledgeRequest,
    IncidentAssignmentRequest,
    IncidentResolveRequest,
    IncidentStatusUpdateRequest,
)
from app.incidents.transitions import (
    InvalidIncidentTransitionError,
)
from app.models import IncidentStatus


def make_incident(
    status: IncidentStatus,
    *,
    acknowledged_at: datetime | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        acknowledged_at=acknowledged_at,
        investigation_started_at=None,
        remediation_started_at=None,
        resolved_at=None,
        resolution_summary=None,
        rca_summary=None,
        remediation_summary=None,
        current_assignee_id=None,
    )


def install_status_repository_mocks(
    monkeypatch,
):
    update_status = MagicMock()
    timeline = MagicMock()
    audit = MagicMock()

    def update_incident_status(
        db,
        incident,
        *,
        status,
        **fields,
    ):
        incident.status = status

        for field_name, value in fields.items():
            setattr(incident, field_name, value)

    update_status.side_effect = (
        update_incident_status
    )

    monkeypatch.setattr(
        service.repository,
        "update_incident_status",
        update_status,
    )
    monkeypatch.setattr(
        service.repository,
        "create_timeline_event",
        timeline,
    )
    monkeypatch.setattr(
        service.repository,
        "create_audit_event",
        audit,
    )

    return update_status, timeline, audit


def test_status_update_sets_acknowledged_timestamp(
    monkeypatch,
):
    db = MagicMock()
    incident = make_incident(
        IncidentStatus.DETECTED
    )
    occurred_at = datetime.now(timezone.utc)

    update_status, timeline, audit = (
        install_status_repository_mocks(
            monkeypatch
        )
    )

    service._stage_status_update(
        db,
        incident,
        IncidentStatusUpdateRequest(
            status=IncidentStatus.ACKNOWLEDGED,
            note="Operator acknowledged incident",
        ),
        actor_user_id="developer-1",
        occurred_at=occurred_at,
    )

    assert incident.status == (
        IncidentStatus.ACKNOWLEDGED
    )
    assert incident.acknowledged_at == occurred_at

    update_status.assert_called_once()
    timeline.assert_called_once()
    audit.assert_called_once()

    assert (
        timeline.call_args.kwargs["actor_user_id"]
        == "developer-1"
    )
    assert (
        audit.call_args.kwargs["actor_id"]
        == "developer-1"
    )


def test_resolution_sets_timestamp_and_summary(
    monkeypatch,
):
    db = MagicMock()
    incident = make_incident(
        IncidentStatus.INVESTIGATING
    )
    occurred_at = datetime.now(timezone.utc)

    _, timeline, audit = (
        install_status_repository_mocks(
            monkeypatch
        )
    )

    service._stage_status_update(
        db,
        incident,
        IncidentStatusUpdateRequest(
            status=IncidentStatus.RESOLVED,
            resolution_summary=(
                "  Service recovered after rollback.  "
            ),
        ),
        actor_user_id="developer-1",
        occurred_at=occurred_at,
    )

    assert incident.status == IncidentStatus.RESOLVED
    assert incident.resolved_at == occurred_at
    assert incident.resolution_summary == (
        "Service recovered after rollback."
    )

    assert timeline.call_args.kwargs["message"] == (
        "Service recovered after rollback."
    )

    audit_details = json.loads(
        audit.call_args.kwargs["details"]
    )

    assert audit_details["resolution_summary"] == (
        "Service recovered after rollback."
    )


def test_service_rejects_empty_resolution_summary(
    monkeypatch,
):
    db = MagicMock()
    incident = make_incident(
        IncidentStatus.INVESTIGATING
    )

    install_status_repository_mocks(
        monkeypatch
    )

    # model_construct deliberately bypasses Pydantic so
    # the service-level defensive validation is tested.
    request = (
        IncidentStatusUpdateRequest.model_construct(
            status=IncidentStatus.RESOLVED,
            note=None,
            resolution_summary="   ",
            rca_summary=None,
            remediation_summary=None,
        )
    )

    with pytest.raises(
        ValueError,
        match="resolution_summary is required",
    ):
        service._stage_status_update(
            db,
            incident,
            request,
            actor_user_id="developer-1",
            occurred_at=datetime.now(timezone.utc),
        )


def test_acknowledge_is_idempotent(
    monkeypatch,
):
    db = MagicMock()
    acknowledged_at = datetime(
        2026,
        7,
        17,
        12,
        0,
        tzinfo=timezone.utc,
    )
    incident = make_incident(
        IncidentStatus.ACKNOWLEDGED,
        acknowledged_at=acknowledged_at,
    )
    expected_detail = object()

    monkeypatch.setattr(
        service.repository,
        "get_incident_by_id",
        MagicMock(return_value=incident),
    )

    stage_status = MagicMock()
    monkeypatch.setattr(
        service,
        "_stage_status_update",
        stage_status,
    )
    monkeypatch.setattr(
        service,
        "get_incident_detail",
        MagicMock(return_value=expected_detail),
    )

    create_assignment = MagicMock()
    create_timeline = MagicMock()
    create_audit = MagicMock()

    monkeypatch.setattr(
        service.repository,
        "create_assignment",
        create_assignment,
    )
    monkeypatch.setattr(
        service.repository,
        "create_timeline_event",
        create_timeline,
    )
    monkeypatch.setattr(
        service.repository,
        "create_audit_event",
        create_audit,
    )

    result = service.acknowledge_incident(
        db,
        incident.id,
        IncidentAcknowledgeRequest(),
        actor_user_id="developer-1",
    )

    assert result is expected_detail
    assert incident.acknowledged_at == acknowledged_at

    stage_status.assert_not_called()
    create_assignment.assert_not_called()
    create_timeline.assert_not_called()
    create_audit.assert_not_called()
    db.commit.assert_not_called()


def test_acknowledge_can_assign_operator(
    monkeypatch,
):
    db = MagicMock()
    incident = make_incident(
        IncidentStatus.DETECTED
    )
    expected_detail = object()
    occurred_at = datetime.now(timezone.utc)

    monkeypatch.setattr(
        service,
        "_utcnow",
        MagicMock(return_value=occurred_at),
    )
    monkeypatch.setattr(
        service.repository,
        "get_incident_by_id",
        MagicMock(return_value=incident),
    )

    def stage_status(
        db,
        incident,
        request,
        *,
        actor_user_id,
        occurred_at,
    ):
        incident.status = (
            IncidentStatus.ACKNOWLEDGED
        )
        incident.acknowledged_at = occurred_at

    monkeypatch.setattr(
        service,
        "_stage_status_update",
        MagicMock(side_effect=stage_status),
    )

    close_assignment = MagicMock()
    create_assignment = MagicMock()
    update_incident = MagicMock()
    create_timeline = MagicMock()
    create_audit = MagicMock()

    monkeypatch.setattr(
        service.repository,
        "close_active_assignment",
        close_assignment,
    )
    monkeypatch.setattr(
        service.repository,
        "create_assignment",
        create_assignment,
    )
    monkeypatch.setattr(
        service.repository,
        "update_incident",
        update_incident,
    )
    monkeypatch.setattr(
        service.repository,
        "create_timeline_event",
        create_timeline,
    )
    monkeypatch.setattr(
        service.repository,
        "create_audit_event",
        create_audit,
    )
    monkeypatch.setattr(
        service,
        "get_incident_detail",
        MagicMock(return_value=expected_detail),
    )

    result = service.acknowledge_incident(
        db,
        incident.id,
        IncidentAcknowledgeRequest(
            assigned_to_user_id="developer-2",
        ),
        actor_user_id="developer-1",
    )

    assert result is expected_detail
    assert incident.acknowledged_at == occurred_at

    close_assignment.assert_called_once()
    create_assignment.assert_called_once()
    update_incident.assert_called_once()
    create_timeline.assert_called_once()
    create_audit.assert_called_once()
    db.commit.assert_called_once()

    assignment_args = (
        create_assignment.call_args.kwargs
    )

    assert assignment_args[
        "assigned_to_user_id"
    ] == "developer-2"
    assert assignment_args[
        "assigned_by_user_id"
    ] == "developer-1"
    assert assignment_args["assigned_at"] == occurred_at


def test_assignment_closes_previous_assignment(
    monkeypatch,
):
    db = MagicMock()
    incident = make_incident(
        IncidentStatus.INVESTIGATING
    )
    occurred_at = datetime.now(timezone.utc)

    assignment = SimpleNamespace(
        id=uuid4(),
        incident_id=incident.id,
        assigned_to_user_id="developer-2",
        assigned_to_user=None,
        assigned_by_user_id="developer-1",
        assigned_by_user=None,
        assignment_note="Operational handoff",
        assigned_at=occurred_at,
        unassigned_at=None,
        is_active=True,
    )

    monkeypatch.setattr(
        service,
        "_utcnow",
        MagicMock(return_value=occurred_at),
    )
    monkeypatch.setattr(
        service.repository,
        "get_incident_by_id",
        MagicMock(return_value=incident),
    )

    close_assignment = MagicMock()
    create_assignment = MagicMock(
        return_value=assignment
    )
    update_incident = MagicMock()
    timeline = MagicMock()
    audit = MagicMock()

    monkeypatch.setattr(
        service.repository,
        "close_active_assignment",
        close_assignment,
    )
    monkeypatch.setattr(
        service.repository,
        "create_assignment",
        create_assignment,
    )
    monkeypatch.setattr(
        service.repository,
        "update_incident",
        update_incident,
    )
    monkeypatch.setattr(
        service.repository,
        "create_timeline_event",
        timeline,
    )
    monkeypatch.setattr(
        service.repository,
        "create_audit_event",
        audit,
    )

    response = service.assign_incident(
        db,
        incident.id,
        IncidentAssignmentRequest(
            assigned_to_user_id="developer-2",
            assignment_note="Operational handoff",
        ),
        assigned_by_user_id="developer-1",
    )

    assert response is not None
    assert response.assigned_to_user_id == (
        "developer-2"
    )
    assert response.assigned_by_user_id == (
        "developer-1"
    )

    close_assignment.assert_called_once_with(
        db,
        incident_id=incident.id,
        unassigned_at=occurred_at,
    )

    create_assignment.assert_called_once()
    update_incident.assert_called_once()
    timeline.assert_called_once()
    audit.assert_called_once()
    db.commit.assert_called_once()


def test_invalid_transition_maps_to_http_409():
    error = InvalidIncidentTransitionError(
        IncidentStatus.DETECTED,
        IncidentStatus.RESOLVED,
    )

    with pytest.raises(HTTPException) as exc:
        _raise_incident_error(error)

    assert exc.value.status_code == 409
    assert "DETECTED -> RESOLVED" in exc.value.detail


def test_normal_value_error_maps_to_http_400():
    with pytest.raises(HTTPException) as exc:
        _raise_incident_error(
            ValueError("Invalid request")
        )

    assert exc.value.status_code == 400


def test_viewer_cannot_modify_incidents():
    checker = require_roles(
        "admin",
        "developer",
    )

    viewer = SimpleNamespace(
        roles=[
            SimpleNamespace(name="viewer"),
        ],
    )

    with pytest.raises(HTTPException) as exc:
        checker(current_user=viewer)

    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "role_name",
    [
        "admin",
        "developer",
    ],
)
def test_admin_and_developer_can_modify_incidents(
    role_name,
):
    checker = require_roles(
        "admin",
        "developer",
    )

    user = SimpleNamespace(
        roles=[
            SimpleNamespace(name=role_name),
        ],
    )

    assert checker(current_user=user) is user


def test_resolution_request_rejects_whitespace():
    with pytest.raises(ValidationError):
        IncidentResolveRequest(
            resolution_summary="   ",
        )
