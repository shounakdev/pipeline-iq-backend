import json

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    Incident,
    IncidentComment,
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
        name="Sprint 7H Comment Test Project",
    )

    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name="comment-test-service",
        service_type="backend",
        owner="platform-team",
    )

    now = datetime.now(timezone.utc)

    incident = Incident(
        title="Comment test incident",
        description="Incident created for comment tests.",
        severity=IncidentSeverity.SEV_3,
        status=IncidentStatus.DETECTED,
        primary_service_id=service.id,
        service_id=service.id,
        environment="test",
        deduplication_key=f"comment-test:{uuid4()}",
        correlation_id=f"comment-test:{uuid4()}",
        failure_started_at=now,
        detected_at=now,
    )

    db.add_all([project, service, incident])
    db.commit()
    db.refresh(incident)

    return incident


def _role_headers(
    client,
    *,
    role: str,
) -> dict[str, str]:
    email = f"comment-{role}@example.com"
    password = f"{role}123"

    registration = register_user(
        client,
        email,
        password,
        role,
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


def _post_comment(
    client,
    *,
    incident_id,
    headers: dict[str, str],
    comment: str,
):
    return client.post(
        f"/api/incidents/{incident_id}/comments",
        headers=headers,
        json={
            "comment": comment,
        },
    )


def _comment_count(
    db: Session,
    incident_id,
) -> int:
    return db.execute(
        select(func.count())
        .select_from(IncidentComment)
        .where(
            IncidentComment.incident_id == incident_id,
        )
    ).scalar_one()


def test_comment_creates_incident_comment(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)
    headers = _role_headers(
        client,
        role="developer",
    )

    comment_text = "Investigating elevated latency."

    response = _post_comment(
        client,
        incident_id=incident.id,
        headers=headers,
        comment=comment_text,
    )

    assert response.status_code == 201, response.text
    assert response.json()["comment"] == comment_text

    db_session.expire_all()

    comment = db_session.execute(
        select(IncidentComment).where(
            IncidentComment.incident_id == incident.id,
            IncidentComment.comment == comment_text,
        )
    ).scalar_one()

    assert comment.incident_id == incident.id
    assert comment.comment == comment_text
    assert comment.author_user_id is not None


def test_comment_creates_timeline_event(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)
    headers = _role_headers(
        client,
        role="developer",
    )

    comment_text = "Checking the latest deployment."

    response = _post_comment(
        client,
        incident_id=incident.id,
        headers=headers,
        comment=comment_text,
    )

    assert response.status_code == 201, response.text

    db_session.expire_all()

    event = db_session.execute(
        select(IncidentTimelineEvent).where(
            IncidentTimelineEvent.incident_id
            == incident.id,
            IncidentTimelineEvent.event_type
            == "INCIDENT_COMMENT_ADDED",
        )
    ).scalar_one()

    assert event.source == "USER"
    assert event.actor_user_id is not None
    assert comment_text in event.message
    assert event.metadata_json["comment_id"] == (
        response.json()["id"]
    )


def test_comment_creates_audit_event(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)
    headers = _role_headers(
        client,
        role="developer",
    )

    comment_text = "Reviewing service logs."

    response = _post_comment(
        client,
        incident_id=incident.id,
        headers=headers,
        comment=comment_text,
    )

    assert response.status_code == 201, response.text

    comment_id = response.json()["id"]

    db_session.expire_all()

    audit_event = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action
            == "INCIDENT_COMMENT_CREATED",
            AuditEvent.entity_id == str(comment_id),
        )
    ).scalar_one()

    details = json.loads(audit_event.details)

    assert audit_event.actor_id is not None
    assert details["incident_id"] == str(incident.id)
    assert details["comment_id"] == str(comment_id)
    assert details["comment_length"] == len(comment_text)
    assert details["method"] == "POST"
    assert details["request_path"] == (
        f"/api/incidents/{incident.id}/comments"
    )


def test_comment_does_not_change_incident_status(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)
    original_status = IncidentStatus(incident.status)

    headers = _role_headers(
        client,
        role="developer",
    )

    response = _post_comment(
        client,
        incident_id=incident.id,
        headers=headers,
        comment="Status must remain unchanged.",
    )

    assert response.status_code == 201, response.text

    db_session.expire_all()
    db_session.refresh(incident)

    assert IncidentStatus(incident.status) == original_status


def test_blank_comment_is_rejected(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)

    headers = _role_headers(
        client,
        role="developer",
    )

    response = _post_comment(
        client,
        incident_id=incident.id,
        headers=headers,
        comment="   \n\t   ",
    )

    assert response.status_code == 422, response.text

    db_session.expire_all()

    assert _comment_count(
        db_session,
        incident.id,
    ) == 0


def test_comment_text_is_preserved(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)

    headers = _role_headers(
        client,
        role="developer",
    )

    original_text = (
        "  First line is intentionally indented.\n"
        "Second line retains trailing spaces.  "
    )

    response = _post_comment(
        client,
        incident_id=incident.id,
        headers=headers,
        comment=original_text,
    )

    assert response.status_code == 201, response.text
    assert response.json()["comment"] == original_text

    db_session.expire_all()

    stored_comment = db_session.execute(
        select(IncidentComment).where(
            IncidentComment.incident_id == incident.id,
        )
    ).scalar_one()

    assert stored_comment.comment == original_text


def test_viewer_cannot_create_comment(
    client,
    db_session: Session,
) -> None:
    incident = _create_incident(db_session)

    headers = _role_headers(
        client,
        role="viewer",
    )

    response = _post_comment(
        client,
        incident_id=incident.id,
        headers=headers,
        comment="Viewer must not create this.",
    )

    assert response.status_code == 403, response.text

    db_session.expire_all()

    comment_count = _comment_count(
        db_session,
        incident.id,
    )

    timeline_count = db_session.execute(
        select(func.count())
        .select_from(IncidentTimelineEvent)
        .where(
            IncidentTimelineEvent.incident_id
            == incident.id,
            IncidentTimelineEvent.event_type
            == "INCIDENT_COMMENT_ADDED",
        )
    ).scalar_one()

    audit_count = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action
            == "INCIDENT_COMMENT_CREATED",
        )
    ).scalar_one()

    assert comment_count == 0
    assert timeline_count == 0
    assert audit_count == 0
