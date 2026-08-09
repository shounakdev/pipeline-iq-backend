from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.chaos import repository
from app.chaos.adapters.mock_adapter import MockChaosAdapter
from app.chaos.config import ChaosSettings
from app.chaos.router import get_chaos_adapter, get_chaos_settings
from app.auth.dependencies import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditEvent,
    ChaosExperiment,
    ChaosObservation,
    ChaosRun,
    ChaosRunStatus,
    ExperimentBenchmark,
    OutboxEvent,
    Project,
    Role,
    Service,
    User,
    user_roles,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


def _settings() -> ChaosSettings:
    return ChaosSettings(
        enabled=True,
        allowed_environments=frozenset({"staging"}),
        allowed_namespaces=frozenset({"platformiq-staging"}),
        allowed_services=frozenset({"payment-service"}),
        max_duration_seconds=600,
        max_concurrent_runs=1,
        watchdog_interval_seconds=1,
        adapter_backend="mock",
    )


@pytest.fixture
def chaos_api(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)
    tables = [
        Role.__table__,
        User.__table__,
        user_roles,
        Project.__table__,
        Service.__table__,
        ChaosExperiment.__table__,
        ChaosRun.__table__,
        ChaosObservation.__table__,
        ExperimentBenchmark.__table__,
        AuditEvent.__table__,
        OutboxEvent.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    db_session = session_factory()
    admin_role = Role(name="admin")
    viewer_role = Role(name="viewer")
    admin = User(email="chaos-admin@example.com", roles=[admin_role])
    viewer = User(email="chaos-viewer@example.com", roles=[viewer_role])
    project = Project(name="Chaos API")
    db_session.add_all([admin, viewer, project])
    db_session.flush()
    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name="payment-service",
        service_type="BACKEND",
    )
    db_session.add(service)
    db_session.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def override_current_user(request: Request):
        user_id = request.headers.get("X-Test-User")
        user = db_session.get(User, user_id)
        if user is None:
            return viewer
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_chaos_settings] = _settings
    app.dependency_overrides[get_chaos_adapter] = MockChaosAdapter
    monkeypatch.setattr(
        "app.chaos.router.execute_chaos_run.delay",
        lambda _run_id: None,
    )
    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "db": db_session,
                "admin": {"X-Test-User": admin.id},
                "viewer": {"X-Test-User": viewer.id},
                "service": service,
            }
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_chaos_settings, None)
        app.dependency_overrides.pop(get_chaos_adapter, None)
        db_session.close()
        Base.metadata.drop_all(bind=engine, tables=reversed(tables))
        engine.dispose()


def _payload(service_id: str, **overrides):
    payload = {
        "name": "Payment service latency validation",
        "description": "Validate detection of network latency.",
        "scenario_type": "NETWORK_DELAY",
        "target_service_id": service_id,
        "target_environment": "staging",
        "target_namespace": "platformiq-staging",
        "failure_config": {
            "latency_ms": 2000,
            "jitter_ms": 200,
            "duration_seconds": 120,
        },
        "expected_behavior": {
            "root_cause": "NETWORK_LATENCY",
            "alert_expected": True,
            "incident_expected": True,
        },
    }
    payload.update(overrides)
    return payload


def _create(client, context, **overrides):
    return client.post(
        "/api/experiments",
        headers=context["admin"],
        json=_payload(context["service"].id, **overrides),
    )


def test_create_list_and_get_experiment(chaos_api):
    client = chaos_api["client"]
    created = _create(client, chaos_api)
    assert created.status_code == 201, created.text
    experiment = created.json()
    assert experiment["scenario_type"] == "NETWORK_DELAY"

    listed = client.get("/api/experiments", headers=chaos_api["viewer"])
    detail = client.get(
        f"/api/experiments/{experiment['id']}",
        headers=chaos_api["viewer"],
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [experiment["id"]]
    assert detail.json()["failure_config"]["latency_ms"] == 2000


def test_unauthorized_run_is_rejected(chaos_api):
    client = chaos_api["client"]
    experiment_id = _create(client, chaos_api).json()["id"]
    response = client.post(
        f"/api/experiments/{experiment_id}/run",
        headers=chaos_api["viewer"],
    )
    assert response.status_code == 403


def test_disabled_experiment_is_rejected(chaos_api):
    client = chaos_api["client"]
    experiment_id = _create(client, chaos_api, enabled=False).json()["id"]
    response = client.post(
        f"/api/experiments/{experiment_id}/run",
        headers=chaos_api["admin"],
    )
    assert response.status_code == 422
    assert "disabled" in response.text


def test_invalid_service_and_production_target_are_rejected(chaos_api):
    client = chaos_api["client"]
    invalid_service = client.post(
        "/api/experiments",
        headers=chaos_api["admin"],
        json=_payload(str(uuid4())),
    )
    production = _create(
        client,
        chaos_api,
        target_environment="production",
        target_namespace="platformiq-production",
    )
    assert invalid_service.status_code == 422
    assert production.status_code == 422


def test_run_details_and_abort_audit(chaos_api):
    client = chaos_api["client"]
    db_session = chaos_api["db"]
    experiment_id = _create(client, chaos_api).json()["id"]
    queued = client.post(
        f"/api/experiments/{experiment_id}/run",
        headers=chaos_api["admin"],
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["status"] == "PENDING"
    run_id = queued.json()["run_id"]

    detail = client.get(
        f"/api/experiments/runs/{run_id}",
        headers=chaos_api["viewer"],
    )
    assert detail.status_code == 200
    assert detail.json()["experiment_id"] == experiment_id
    assert detail.json()["observations"] == []

    aborted = client.post(
        f"/api/experiments/runs/{run_id}/abort",
        headers=chaos_api["admin"],
    )
    assert aborted.status_code == 200, aborted.text
    assert aborted.json()["status"] == "ABORTED"

    audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.action == "CHAOS_RUN_ABORTED",
            AuditEvent.entity_id == run_id,
        )
        .one()
    )
    assert audit.actor_id is not None


def test_benchmarks_are_returned_in_chronological_order(
    chaos_api,
):
    client = chaos_api["client"]
    db_session = chaos_api["db"]
    experiment_id = _create(client, chaos_api).json()["id"]
    experiment = repository.get_experiment_by_id(
        db_session,
        UUID(experiment_id),
    )
    base = datetime.now(timezone.utc)
    benchmarks = []
    for index, calculated_at in enumerate((base + timedelta(minutes=2), base)):
        run = repository.create_run(
            db_session,
            experiment_id=experiment.id,
            status=ChaosRunStatus.COMPLETED,
            started_at=base + timedelta(seconds=index),
            duration_seconds=1,
        )
        benchmarks.append(
            repository.save_benchmark(
                db_session,
                chaos_run_id=run.id,
                values={"calculated_at": calculated_at},
            )
        )
    db_session.commit()

    response = client.get(
        f"/api/experiments/{experiment_id}/benchmarks",
        headers=chaos_api["viewer"],
    )
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [
        str(benchmarks[1].id),
        str(benchmarks[0].id),
    ]