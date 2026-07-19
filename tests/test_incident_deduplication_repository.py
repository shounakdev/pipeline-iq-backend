"""Repository tests for Sprint 7E incident correlation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.incidents import repository
from app.incidents.rules import (
    build_deduplication_key,
    build_deduplication_lock_id,
)
from app.models import (
    Incident,
    IncidentSeverity,
    IncidentStatus,
    Project,
    Service,
)


def _create_service(db: Session) -> Service:
    project = Project(
        id=str(uuid4()),
        name="Sprint 7E Test Project",
    )
    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name="critical-api",
        service_type="backend",
        owner="platform-team",
    )

    db.add_all([project, service])
    db.flush()

    return service


def _create_incident(
    db: Session,
    *,
    service: Service,
    deduplication_key: str,
    detected_at: datetime,
    status: IncidentStatus = IncidentStatus.DETECTED,
    resolved_at: datetime | None = None,
) -> Incident:
    incident = Incident(
        title="Test reliability incident",
        description="Created by Sprint 7E repository tests.",
        severity=IncidentSeverity.SEV_3,
        status=status,
        primary_service_id=service.id,
        environment="production",
        deduplication_key=deduplication_key,
        failure_started_at=detected_at,
        detected_at=detected_at,
        resolved_at=resolved_at,
        service_id=service.id,
        correlation_id=deduplication_key,
    )

    db.add(incident)
    db.flush()

    return incident


def test_returns_matching_open_incident_inside_window(
    db_session: Session,
) -> None:
    service = _create_service(db_session)
    alert_time = datetime.now(timezone.utc)

    deduplication_key = build_deduplication_key(
        service.id,
        "production",
        "availability-slo",
    )

    incident = _create_incident(
        db_session,
        service=service,
        deduplication_key=deduplication_key,
        detected_at=alert_time - timedelta(minutes=10),
    )

    found = repository.find_open_incident_by_deduplication_key(
        db_session,
        deduplication_key,
        correlation_cutoff=alert_time - timedelta(minutes=30),
    )

    assert found is not None
    assert found.id == incident.id


def test_returns_incident_at_exact_window_boundary(
    db_session: Session,
) -> None:
    service = _create_service(db_session)
    alert_time = datetime.now(timezone.utc)

    deduplication_key = build_deduplication_key(
        service.id,
        "production",
        "latency-slo",
    )
    boundary_time = alert_time - timedelta(minutes=30)

    incident = _create_incident(
        db_session,
        service=service,
        deduplication_key=deduplication_key,
        detected_at=boundary_time,
    )

    found = repository.find_open_incident_by_deduplication_key(
        db_session,
        deduplication_key,
        correlation_cutoff=boundary_time,
    )

    assert found is not None
    assert found.id == incident.id


def test_does_not_return_incident_outside_window(
    db_session: Session,
) -> None:
    service = _create_service(db_session)
    alert_time = datetime.now(timezone.utc)

    deduplication_key = build_deduplication_key(
        service.id,
        "production",
        "error-rate-slo",
    )

    _create_incident(
        db_session,
        service=service,
        deduplication_key=deduplication_key,
        detected_at=alert_time - timedelta(minutes=31),
    )

    found = repository.find_open_incident_by_deduplication_key(
        db_session,
        deduplication_key,
        correlation_cutoff=alert_time - timedelta(minutes=30),
    )

    assert found is None


def test_does_not_return_resolved_incident_inside_window(
    db_session: Session,
) -> None:
    service = _create_service(db_session)
    alert_time = datetime.now(timezone.utc)

    deduplication_key = build_deduplication_key(
        service.id,
        "production",
        "availability-slo",
    )

    _create_incident(
        db_session,
        service=service,
        deduplication_key=deduplication_key,
        detected_at=alert_time - timedelta(minutes=5),
        status=IncidentStatus.RESOLVED,
        resolved_at=alert_time - timedelta(minutes=1),
    )

    found = repository.find_open_incident_by_deduplication_key(
        db_session,
        deduplication_key,
        correlation_cutoff=alert_time - timedelta(minutes=30),
    )

    assert found is None


def test_does_not_return_incident_with_different_key(
    db_session: Session,
) -> None:
    service = _create_service(db_session)
    alert_time = datetime.now(timezone.utc)

    stored_key = build_deduplication_key(
        service.id,
        "production",
        "availability-slo",
    )
    requested_key = build_deduplication_key(
        service.id,
        "production",
        "latency-slo",
    )

    _create_incident(
        db_session,
        service=service,
        deduplication_key=stored_key,
        detected_at=alert_time - timedelta(minutes=5),
    )

    found = repository.find_open_incident_by_deduplication_key(
        db_session,
        requested_key,
        correlation_cutoff=alert_time - timedelta(minutes=30),
    )

    assert found is None

def test_deduplication_lock_blocks_competing_transaction(
    db_session: Session,
) -> None:
    lock_id = build_deduplication_lock_id(
        "service-1:production:slo-1",
    )

    repository.acquire_incident_deduplication_lock(
        db_session,
        lock_id=lock_id,
    )

    bind = db_session.get_bind()

    with bind.connect() as competing_connection:
        acquired = competing_connection.execute(
            select(
                func.pg_try_advisory_xact_lock(lock_id),
            )
        ).scalar_one()

        assert acquired is False

