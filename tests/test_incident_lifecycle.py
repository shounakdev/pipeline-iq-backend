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
    IncidentAssignRequest,
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
        incident_number="INC-TEST-001",
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
            setattr(
                incident,
                field_name,
                value,
            )

    update_status.side_effect = update_incident_status

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
            reason="Operator acknowledged incident",
        ),
        actor_user_id="developer-1",
        occurred_at=occurred_at,
    )

    assert (
        incident.status
        == IncidentStatus.ACKNOWLEDGED
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
        timeline.call_args.kwargs["message"]
        == "Operator acknowledged incident"
    )

    assert (
        audit.call_args.kwargs["actor_id"]
        == "developer-1"
    )

    audit_details = audit.call_args.kwargs["details"]

    assert audit_details["from_status"] == "DETECTED"
    assert (
        audit_details["to_status"]
        == "ACKNOWLEDGED"
    )
    assert audit_details["reason"] == (
        "Operator acknowledged incident"
    )


def test_resolution_sets_timestamp_and_summary(
    monkeypatch,
):
    db = MagicMock()
    incident = make_incident(
        IncidentStatus.REMEDIATING
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
            reason=(
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

    audit_details = audit.call_args.kwargs["details"]

    assert audit_details["from_status"] == (
        "REMEDIATING"
    )
    assert audit_details["to_status"] == "RESOLVED"
    assert audit_details["resolution_summary"] == (
        "Service recovered after rollback."
    )


def test_service_rejects_empty_resolution_reason(
    monkeypatch,
):
    db = MagicMock()
    incident = make_incident(
        IncidentStatus.REMEDIATING
    )

    update_status, timeline, audit = (
        install_status_repository_mocks(
            monkeypatch
        )
    )

    # Bypass Pydantic validation to prove that the service also
    # defensively rejects an empty resolution reason.
    request = IncidentStatusUpdateRequest.model_construct(
        status=IncidentStatus.RESOLVED,
        reason="   ",
    )

    with pytest.raises(
        service.IncidentConflictError,
        match="resolution reason is required",
    ):
        service._stage_status_update(
            db,
            incident,
            request,
            actor_user_id="developer-1",
            occurred_at=datetime.now(timezone.utc),
        )

    assert incident.status == IncidentStatus.REMEDIATING
    assert incident.resolved_at is None

    update_status.assert_not_called()
    timeline.assert_not_called()
    audit.assert_not_called()


def test_repeated_acknowledgement_is_rejected(
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

    monkeypatch.setattr(
        service.repository,
        "get_incident_by_id",
        MagicMock(return_value=incident),
    )

    update_status = MagicMock()
    create_assignment = MagicMock()
    create_timeline = MagicMock()
    create_audit = MagicMock()
    update_incident = MagicMock()
    get_detail = MagicMock()

    monkeypatch.setattr(
        service.repository,
        "update_incident_status",
        update_status,
    )
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
    monkeypatch.setattr(
        service.repository,
        "update_incident",
        update_incident,
    )
    monkeypatch.setattr(
        service,
        "get_incident_detail",
        get_detail,
    )

    with pytest.raises(
        service.IncidentConflictError,
        match="already in status ACKNOWLEDGED",
    ):
        service.acknowledge_incident(
            db,
            incident.id,
            IncidentAcknowledgeRequest(),
            actor_user_id="developer-1",
        )

    assert incident.acknowledged_at == acknowledged_at

    update_status.assert_not_called()
    create_assignment.assert_not_called()
    create_timeline.assert_not_called()
    create_audit.assert_not_called()
    update_incident.assert_not_called()
    get_detail.assert_not_called()

    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_acknowledge_can_assign_to_self(
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
        timeline_metadata=None,
        audit_metadata=None,
    ):
        assert request.status == (
            IncidentStatus.ACKNOWLEDGED
        )
        assert request.reason == (
            "Acknowledged and taking ownership"
        )
        assert actor_user_id == "developer-1"

        assert timeline_metadata == {
            "assign_to_self": True,
            "assigned_to_user_id": "developer-1",
        }
        assert audit_metadata == {
            "assign_to_self": True,
            "assigned_to_user_id": "developer-1",
        }

        incident.status = IncidentStatus.ACKNOWLEDGED
        incident.acknowledged_at = occurred_at

    stage_status_mock = MagicMock(
        side_effect=stage_status
    )

    monkeypatch.setattr(
        service,
        "_stage_status_update",
        stage_status_mock,
    )

    close_assignment = MagicMock()
    create_assignment = MagicMock()
    update_incident = MagicMock()

    monkeypatch.setattr(
        service.repository,
        "close_current_assignment",
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
        service,
        "get_incident_detail",
        MagicMock(return_value=expected_detail),
    )

    result = service.acknowledge_incident(
        db,
        incident.id,
        IncidentAcknowledgeRequest(
            note="Acknowledged and taking ownership",
            assign_to_self=True,
        ),
        actor_user_id="developer-1",
    )

    assert result is expected_detail
    assert (
        incident.status
        == IncidentStatus.ACKNOWLEDGED
    )
    assert incident.acknowledged_at == occurred_at

    stage_status_mock.assert_called_once()

    close_assignment.assert_called_once_with(
        db,
        incident_id=incident.id,
        unassigned_at=occurred_at,
    )

    create_assignment.assert_called_once_with(
        db,
        incident_id=incident.id,
        assigned_to_user_id="developer-1",
        assigned_by_user_id="developer-1",
        assignment_note=(
            "Acknowledged and taking ownership"
        ),
        assigned_at=occurred_at,
    )

    update_incident.assert_called_once_with(
        db,
        incident,
        current_assignee_id="developer-1",
    )

    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(incident)


def test_assignment_closes_previous_assignment(
    monkeypatch,
):
    db = MagicMock()
    incident = make_incident(
        IncidentStatus.INVESTIGATING
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

    close_assignment = MagicMock()
    create_assignment = MagicMock()
    update_incident = MagicMock()
    timeline = MagicMock()
    audit = MagicMock()
    get_detail = MagicMock(
        return_value=expected_detail
    )

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
    monkeypatch.setattr(
        service,
        "get_incident_detail",
        get_detail,
    )

    response = service.assign_incident(
        db,
        incident.id,
        IncidentAssignRequest(
            assigned_to_user_id="developer-2",
            note="Operational handoff",
        ),
        assigned_by_user_id="developer-1",
    )

    assert response is expected_detail

    close_assignment.assert_called_once_with(
        db,
        incident_id=incident.id,
        unassigned_at=occurred_at,
    )

    create_assignment.assert_called_once_with(
        db,
        incident_id=incident.id,
        assigned_to_user_id="developer-2",
        assigned_by_user_id="developer-1",
        assignment_note="Operational handoff",
        assigned_at=occurred_at,
    )

    update_incident.assert_called_once_with(
        db,
        incident,
        current_assignee_id="developer-2",
    )

    timeline.assert_called_once()
    timeline_kwargs = timeline.call_args.kwargs

    assert timeline_kwargs["incident_id"] == incident.id
    assert timeline_kwargs["event_type"] == (
        "OPERATOR_ASSIGNED"
    )
    assert timeline_kwargs["message"] == (
        "Operational handoff"
    )
    assert timeline_kwargs["actor_user_id"] == (
        "developer-1"
    )

    metadata = timeline_kwargs["metadata_json"]

    assert metadata["assigned_to_user_id"] == (
        "developer-2"
    )
    assert "assigned_to_user_email" in metadata
    assert "previous_assignee_user_id" in metadata

    audit.assert_called_once()
    get_detail.assert_called_once_with(
        db,
        incident.id,
    )

    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(incident)


def test_invalid_transition_maps_to_http_409():
    error = InvalidIncidentTransitionError(
        IncidentStatus.DETECTED,
        IncidentStatus.RESOLVED,
    )

    with pytest.raises(HTTPException) as exc:
        _raise_incident_error(error)

    assert exc.value.status_code == 409
    assert (
        "DETECTED -> RESOLVED"
        in exc.value.detail
    )


def test_normal_value_error_maps_to_http_400():
    with pytest.raises(HTTPException) as exc:
        _raise_incident_error(
            ValueError("Invalid request")
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid request"


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