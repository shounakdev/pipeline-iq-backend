import json

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
        name="Sprint 7H Audit Test Project",
    )

    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name="audit-test-service",
        service_type="backend",
        owner="platform-team",
    )

    now = datetime.now(timezone.utc)

    incident = Incident(
        title="Audit logging test incident",
        description="Incident created for audit tests.",
        severity=IncidentSeverity.SEV_3,
        status=IncidentStatus.DETECTED,
        primary_service_id=service.id,
        service_id=service.id,
        environment="test",
        deduplication_key=f"audit-test:{uuid4()}",
        correlation_id=f"audit-test:{uuid4()}",
        failure_started_at=now,
        detected_at=now,
    )

    db.add_all(
        [
            project,
            service,
            incident,
        ]
    )
    db.commit()
    db.refresh(incident)

    return incident


def _developer_headers(
    client,
) -> dict[str, str]:
    email = "audit-developer@example.com"
    password = "developer123"

    registration = register_user(
        client,
        email,
        password,
        "developer",
    )

    assert registration.status_code in {
        200,
        201,
    }, registration.text

    token = login_user(
        client,
        email,
        password,
    )

    return auth_headers(token)


def _acknowledge_incident(
    client,
    *,
    incident_id,
    headers: dict[str, str],
):
    return client.post(
        (
            f"/api/incidents/"
            f"{incident_id}/acknowledge"
        ),
        headers=headers,
        json={},
    )


def _acknowledgement_timeline_count(
    db: Session,
    incident_id,
) -> int:
    return db.execute(
        select(func.count())
        .select_from(IncidentTimelineEvent)
        .where(
            IncidentTimelineEvent.incident_id
            == incident_id,
            IncidentTimelineEvent.event_type
            == "INCIDENT_ACKNOWLEDGED",
        )
    ).scalar_one()


def _acknowledgement_audit_count(
    db: Session,
    incident_id,
) -> int:
    return db.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action
            == "INCIDENT_ACKNOWLEDGED",
            AuditEvent.entity_id
            == str(incident_id),
        )
    ).scalar_one()


def _enum_value(value):
    return getattr(
        value,
        "value",
        value,
    )


def test_status_change_creates_timeline_and_audit(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)
    headers = _developer_headers(client)

    response = _acknowledge_incident(
        client,
        incident_id=incident.id,
        headers=headers,
    )

    assert response.status_code == 200, (
        response.text
    )
    assert response.json()["incident"]["status"] == (
        "ACKNOWLEDGED"
    )

    db_session.expire_all()
    db_session.refresh(incident)

    assert IncidentStatus(incident.status) == (
        IncidentStatus.ACKNOWLEDGED
    )
    assert incident.acknowledged_at is not None

    timeline_event = db_session.execute(
        select(IncidentTimelineEvent).where(
            IncidentTimelineEvent.incident_id
            == incident.id,
            IncidentTimelineEvent.event_type
            == "INCIDENT_ACKNOWLEDGED",
        )
    ).scalar_one()

    assert timeline_event.actor_user_id is not None
    assert _enum_value(
        timeline_event.from_status
    ) == "DETECTED"
    assert _enum_value(
        timeline_event.to_status
    ) == "ACKNOWLEDGED"

    audit_event = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action
            == "INCIDENT_ACKNOWLEDGED",
            AuditEvent.entity_id
            == str(incident.id),
        )
    ).scalar_one()

    details = json.loads(
        audit_event.details
    )

    assert audit_event.actor_id is not None
    assert details["from_status"] == "DETECTED"
    assert (
        details["to_status"]
        == "ACKNOWLEDGED"
    )


def test_duplicate_acknowledgement_returns_conflict_without_duplicate_events(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)
    headers = _developer_headers(client)

    first_response = _acknowledge_incident(
        client,
        incident_id=incident.id,
        headers=headers,
    )

    assert first_response.status_code == 200, (
        first_response.text
    )
    assert (
        first_response.json()["incident"]["status"]
        == "ACKNOWLEDGED"
    )

    db_session.expire_all()
    db_session.refresh(incident)

    first_acknowledged_at = (
        incident.acknowledged_at
    )

    timeline_count_after_first = (
        _acknowledgement_timeline_count(
            db_session,
            incident.id,
        )
    )

    audit_count_after_first = (
        _acknowledgement_audit_count(
            db_session,
            incident.id,
        )
    )

    assert first_acknowledged_at is not None
    assert timeline_count_after_first == 1
    assert audit_count_after_first == 1

    second_response = _acknowledge_incident(
        client,
        incident_id=incident.id,
        headers=headers,
    )

    assert second_response.status_code == 409, (
        second_response.text
    )
    assert second_response.json() == {
        "detail": (
            "Incident is already in status "
            "ACKNOWLEDGED"
        )
    }

    db_session.expire_all()
    db_session.refresh(incident)

    assert IncidentStatus(incident.status) == (
        IncidentStatus.ACKNOWLEDGED
    )
    assert incident.acknowledged_at == (
        first_acknowledged_at
    )

    timeline_count_after_second = (
        _acknowledgement_timeline_count(
            db_session,
            incident.id,
        )
    )

    audit_count_after_second = (
        _acknowledgement_audit_count(
            db_session,
            incident.id,
        )
    )

    assert (
        timeline_count_after_second
        == timeline_count_after_first
    )
    assert (
        audit_count_after_second
        == audit_count_after_first
    )