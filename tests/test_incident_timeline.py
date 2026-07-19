import json

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.incidents import repository
from app.models import (
    AuditEvent,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    IncidentTimelineEvent,
    Project,
    Service,
)
from tests.conftest import (
    auth_headers,
    login_user,
    register_user,
)


def _create_incident(db: Session) -> Incident:
    project = Project(
        id=str(uuid4()),
        name="Sprint 7H Timeline Test Project",
    )

    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name="timeline-test-service",
        service_type="backend",
        owner="platform-team",
    )

    now = datetime.now(timezone.utc)

    incident = Incident(
        title="Timeline ordering test incident",
        description="Incident created for Sprint 7H tests.",
        severity=IncidentSeverity.SEV_3,
        status=IncidentStatus.DETECTED,
        primary_service_id=service.id,
        service_id=service.id,
        environment="test",
        deduplication_key=f"timeline-test:{uuid4()}",
        correlation_id=f"timeline-test:{uuid4()}",
        failure_started_at=now,
        detected_at=now,
    )

    db.add_all([project, service, incident])
    db.commit()
    db.refresh(incident)

    return incident


def _developer_headers(client) -> dict[str, str]:
    email = "timeline-developer@example.com"
    password = "developer123"

    registration = register_user(
        client,
        email,
        password,
        "developer",
    )

    assert registration.status_code in {200, 201}, (
        registration.text
    )

    token = login_user(
        client,
        email,
        password,
    )

    return auth_headers(token)


def _collect_keys(value) -> set[str]:
    keys: set[str] = set()

    if isinstance(value, dict):
        keys.update(value.keys())

        for nested_value in value.values():
            keys.update(_collect_keys(nested_value))

    elif isinstance(value, list):
        for item in value:
            keys.update(_collect_keys(item))

    return keys


def test_timeline_is_ordered_by_occurred_at_then_id(
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)

    occurred_at = datetime(
        2026,
        7,
        18,
        10,
        30,
        tzinfo=timezone.utc,
    )

    lower_id = UUID(
        "00000000-0000-0000-0000-000000000001"
    )
    higher_id = UUID(
        "00000000-0000-0000-0000-000000000002"
    )

    # Reverse created_at deliberately. A repository that incorrectly
    # orders by created_at will return the higher UUID first.
    higher_id_event = IncidentTimelineEvent(
        id=higher_id,
        incident_id=incident.id,
        event_type="TEST_HIGHER_ID",
        source="TEST",
        message="Higher UUID event",
        metadata_json={},
        occurred_at=occurred_at,
        created_at=occurred_at,
    )

    lower_id_event = IncidentTimelineEvent(
        id=lower_id,
        incident_id=incident.id,
        event_type="TEST_LOWER_ID",
        source="TEST",
        message="Lower UUID event",
        metadata_json={},
        occurred_at=occurred_at,
        created_at=occurred_at + timedelta(seconds=1),
    )

    # Insert the higher UUID first intentionally.
    db_session.add_all(
        [
            higher_id_event,
            lower_id_event,
        ]
    )
    db_session.commit()

    events = repository.get_incident_timeline(
        db_session,
        incident.id,
    )

    actual_order = [
        (event.occurred_at, event.id)
        for event in events
    ]

    assert actual_order == sorted(
        actual_order,
        key=lambda item: (item[0], item[1]),
    )

    matching_ids = [
        event.id
        for event in events
        if event.id in {lower_id, higher_id}
    ]

    assert matching_ids == [
        lower_id,
        higher_id,
    ]


def test_timeline_response_does_not_expose_audit_details(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)
    headers = _developer_headers(client)

    repository.create_timeline_event(
        db_session,
        incident_id=incident.id,
        event_type="INCIDENT_DETECTED",
        source="SYSTEM",
        message="Incident detected.",
        occurred_at=incident.detected_at,
    )

    secret_value = (
        "RAW-AUDIT-DETAIL-MUST-NOT-APPEAR"
    )

    audit_event = AuditEvent(
        actor_id=None,
        action="TEST_PRIVATE_AUDIT_EVENT",
        entity_type="Incident",
        entity_id=str(incident.id),
        details=json.dumps(
            {
                "secret_value": secret_value,
                "private_request_path": (
                    "/internal/private/audit"
                ),
            }
        ),
    )

    db_session.add(audit_event)
    db_session.commit()

    response = client.get(
        f"/api/incidents/{incident.id}/timeline",
        headers=headers,
    )

    assert response.status_code == 200, response.text

    payload = response.json()
    response_keys = _collect_keys(payload)

    assert "audit_events" not in response_keys
    assert "audit_details" not in response_keys
    assert secret_value not in response.text
    assert "/internal/private/audit" not in response.text
