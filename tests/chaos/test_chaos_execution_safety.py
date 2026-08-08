import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.chaos import repository
from app.chaos.config import ChaosSettings
from app.chaos.exceptions import ChaosConflictError, ChaosValidationError
from app.chaos.kubernetes_adapter import (
    CreatedChaosResource,
    build_podchaos_manifest,
)
from app.chaos.schemas import ChaosRunCreateRequest
from app.chaos.service import _validate_request, create_chaos_run
from app.database import Base
from app.models import (
    ChaosExperiment,
    ChaosRun,
    ChaosScenarioType,
    Project,
    Service,
    User,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


class FakeAdapter:
    def __init__(self):
        self.created = []

    def create_podchaos(self, *, namespace, manifest):
        self.created.append((namespace, manifest))
        return CreatedChaosResource(
            kind="PodChaos",
            name=manifest["metadata"]["name"],
            uid="fake-uid",
        )


@pytest.fixture
def safety_db():
    engine = create_engine("sqlite:///:memory:")
    tables = [
    User.__table__,
    Project.__table__,
    Service.__table__,
    ChaosExperiment.__table__,
    ChaosRun.__table__,
    repository.ChaosObservation.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    session = sessionmaker(bind=engine)()
    user = User(
        id="operator-1",
        email="chaos-operator@example.com",
        password_hash="not-used",
        full_name="Chaos Operator",
        is_active=True,
    )
    project = Project(id="project-1", name="Chaos Project", created_by=user.id)
    service = Service(
        id="service-1",
        project_id=project.id,
        name="chaos-test-service",
        service_type="BACKEND",
        owner="platform-team",
    )
    session.add_all([user, project, service])
    session.flush()
    repository.create_experiment(
        session,
        name="Kill one disposable pod",
        scenario_type=ChaosScenarioType.POD_KILL,
        target_service_id=service.id,
        target_environment="development",
        target_namespace="platformiq-dev",
        failure_type="POD_KILL",
        failure_config={},
        expected_behavior={},
        created_by=user.id,
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=reversed(tables))
        engine.dispose()


def settings(**overrides):
    values = {
        "enabled": True,
        "allowed_environments": frozenset({"development"}),
        "allowed_namespaces": frozenset({"platformiq-dev"}),
        "allowed_services": frozenset({"chaos-test-service"}),
        "max_duration_seconds": 600,
        "max_concurrent_runs": 1,
        "watchdog_interval_seconds": 30,
    }
    values.update(overrides)
    return ChaosSettings(**values)


def request(**overrides):
    values = {
        "environment": "development",
        "namespace": "platformiq-dev",
        "service": "chaos-test-service",
        "durationSeconds": 30,
        "cleanupBehavior": "delete",
    }
    values.update(overrides)
    return ChaosRunCreateRequest.model_validate(values)


@pytest.mark.parametrize(
    "payload",
    [
        {"durationSeconds": 0},
        {"durationSeconds": -1},
        {"durationSeconds": None},
    ],
)
def test_duration_must_be_present_and_positive(payload):
    with pytest.raises(ValidationError):
        request(**payload)


def test_production_is_rejected_before_database_or_kubernetes():
    with pytest.raises(ChaosValidationError, match="Production"):
        _validate_request(
            request(
                environment="production",
                namespace="platformiq-production",
            ),
            settings(
                allowed_environments=frozenset({"production"}),
                allowed_namespaces=frozenset({"platformiq-production"}),
            ),
        )


def test_namespace_service_and_duration_are_allowlisted():
    with pytest.raises(ChaosValidationError, match="Namespace"):
        _validate_request(request(namespace="default"), settings())
    with pytest.raises(ChaosValidationError, match="Service"):
        _validate_request(request(service="orders-api"), settings())
    with pytest.raises(ChaosValidationError, match="Duration"):
        _validate_request(request(durationSeconds=601), settings())


def test_manifest_uses_only_server_generated_scope_and_identity():
    manifest = build_podchaos_manifest(
        run_id="abc123",
        environment="development",
        namespace="platformiq-dev",
        service_name="chaos-test-service",
        operator_id="user-123",
        deadline="2026-08-08T20:30:00+00:00",
        duration_seconds=30,
    )
    assert manifest["spec"]["duration"] == "30s"
    assert manifest["spec"]["selector"] == {
        "namespaces": ["platformiq-dev"],
        "labelSelectors": {
            "app.kubernetes.io/name": "chaos-test-service"
        },
    }
    assert (
        manifest["metadata"]["annotations"]["platformiq.io/operator"]
        == "user-123"
    )


def test_duplicate_active_run_conflicts_before_second_kubernetes_call(
    safety_db,
):
    adapter = FakeAdapter()
    create_chaos_run(
        db=safety_db,
        request=request(),
        operator_id="operator-1",
        adapter=adapter,
        settings=settings(),
    )
    with pytest.raises(ChaosConflictError):
        create_chaos_run(
            db=safety_db,
            request=request(),
            operator_id="operator-1",
            adapter=adapter,
            settings=settings(),
        )
    assert len(adapter.created) == 1


def test_followup_migration_adds_atomic_safety_indexes():
    backend_root = Path(__file__).resolve().parents[2]
    path = backend_root / "alembic" / "versions" / (
        "e7b8c9d0a1f2_add_chaos_execution_safety.py"
    )
    spec = importlib.util.spec_from_file_location("chaos_safety", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "c9a8e7d6f5b4"
    source = path.read_text()
    assert "one_active_chaos_run_per_target" in source
    assert "one_active_chaos_run_global" in source
    assert '[sa.text("(1)")]' in source
    assert "deadline_at" in source
