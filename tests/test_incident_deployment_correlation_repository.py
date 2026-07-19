"""Repository tests for Sprint 7F deployment correlation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.incidents import repository
from app.models import Deployment, Environment, Project, Service


CORRELATION_WINDOW_MINUTES = 60


def _create_service(
    db: Session,
    *,
    name: str = "payment-service",
) -> Service:
    project = Project(
        id=str(uuid4()),
        name=f"Sprint 7F Project {uuid4()}",
    )
    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name=name,
        service_type="backend",
        owner="platform-team",
    )

    db.add_all([project, service])
    db.flush()

    return service


def _create_environment(
    db: Session,
    *,
    service: Service,
    name: str,
) -> Environment:
    environment = Environment(
        id=str(uuid4()),
        service_id=service.id,
        name=name,
        is_active=True,
    )

    db.add(environment)
    db.flush()

    return environment


def _create_deployment(
    db: Session,
    *,
    service: Service,
    environment: Environment,
    created_at: datetime,
    image_tag: str,
) -> Deployment:
    deployment = Deployment(
        service_id=service.id,
        environment_id=environment.id,
        service_name=service.name,
        image_tag=image_tag,
        deployment_version=image_tag,
        created_at=created_at,
        deployed_at=created_at,
    )

    db.add(deployment)
    db.flush()

    return deployment


def _find(
    db: Session,
    *,
    service: Service,
    environment: str,
    detected_at: datetime,
) -> Deployment | None:
    return repository.find_suspected_deployment(
        db,
        service_id=service.id,
        environment=environment,
        detected_at=detected_at,
        correlation_window_minutes=CORRELATION_WINDOW_MINUTES,
    )


def test_returns_latest_matching_deployment(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service = _create_service(db_session)
    environment = _create_environment(
        db_session,
        service=service,
        name="production",
    )

    _create_deployment(
        db_session,
        service=service,
        environment=environment,
        created_at=detected_at - timedelta(minutes=40),
        image_tag="payment-service:v1",
    )
    latest = _create_deployment(
        db_session,
        service=service,
        environment=environment,
        created_at=detected_at - timedelta(minutes=10),
        image_tag="payment-service:v2",
    )

    found = _find(
        db_session,
        service=service,
        environment="production",
        detected_at=detected_at,
    )

    assert found is not None
    assert found.id == latest.id
    assert found.image_tag == "payment-service:v2"


def test_excludes_deployment_for_different_service(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)

    incident_service = _create_service(
        db_session,
        name="payment-service",
    )
    other_service = _create_service(
        db_session,
        name="inventory-service",
    )

    _create_environment(
        db_session,
        service=incident_service,
        name="production",
    )
    other_environment = _create_environment(
        db_session,
        service=other_service,
        name="production",
    )

    _create_deployment(
        db_session,
        service=other_service,
        environment=other_environment,
        created_at=detected_at - timedelta(minutes=5),
        image_tag="inventory-service:v1",
    )

    found = _find(
        db_session,
        service=incident_service,
        environment="production",
        detected_at=detected_at,
    )

    assert found is None


def test_excludes_deployment_for_different_environment(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service = _create_service(db_session)
    staging = _create_environment(
        db_session,
        service=service,
        name="staging",
    )

    _create_deployment(
        db_session,
        service=service,
        environment=staging,
        created_at=detected_at - timedelta(minutes=5),
        image_tag="payment-service:staging",
    )

    found = _find(
        db_session,
        service=service,
        environment="production",
        detected_at=detected_at,
    )

    assert found is None


def test_excludes_deployment_after_detection(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service = _create_service(db_session)
    environment = _create_environment(
        db_session,
        service=service,
        name="production",
    )

    _create_deployment(
        db_session,
        service=service,
        environment=environment,
        created_at=detected_at + timedelta(seconds=1),
        image_tag="payment-service:future",
    )

    found = _find(
        db_session,
        service=service,
        environment="production",
        detected_at=detected_at,
    )

    assert found is None


def test_excludes_deployment_older_than_window(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service = _create_service(db_session)
    environment = _create_environment(
        db_session,
        service=service,
        name="production",
    )

    _create_deployment(
        db_session,
        service=service,
        environment=environment,
        created_at=detected_at - timedelta(minutes=61),
        image_tag="payment-service:old",
    )

    found = _find(
        db_session,
        service=service,
        environment="production",
        detected_at=detected_at,
    )

    assert found is None


def test_accepts_deployment_at_exact_window_boundary(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service = _create_service(db_session)
    environment = _create_environment(
        db_session,
        service=service,
        name=" Production ",
    )

    boundary_deployment = _create_deployment(
        db_session,
        service=service,
        environment=environment,
        created_at=detected_at - timedelta(
            minutes=CORRELATION_WINDOW_MINUTES,
        ),
        image_tag="payment-service:boundary",
    )

    found = _find(
        db_session,
        service=service,
        environment="PRODUCTION",
        detected_at=detected_at,
    )

    assert found is not None
    assert found.id == boundary_deployment.id


def test_returns_none_when_no_deployments_exist(
    db_session: Session,
) -> None:
    detected_at = datetime.now(timezone.utc)
    service = _create_service(db_session)

    _create_environment(
        db_session,
        service=service,
        name="production",
    )

    found = _find(
        db_session,
        service=service,
        environment="production",
        detected_at=detected_at,
    )

    assert found is None
