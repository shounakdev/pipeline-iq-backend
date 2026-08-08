import pytest
from kubernetes.client.exceptions import ApiException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.chaos import repository
from app.chaos.adapters.chaos_mesh_adapter import ChaosMeshAdapter
from app.chaos.adapters.mock_adapter import MockChaosAdapter
from app.chaos.config import ChaosSettings
from app.chaos.exceptions import ChaosKubernetesError
from app.chaos.kubernetes_adapter import build_podchaos_manifest
from app.chaos.schemas import ChaosRunCreateRequest
from app.chaos.service import cleanup_chaos_run, create_chaos_run
from app.database import Base
from app.models import (
    ChaosExperiment,
    ChaosObservationType,
    ChaosRun,
    ChaosRunStatus,
    ChaosScenarioType,
    Project,
    Service,
    User,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


class RecordingApi:
    def __init__(self):
        self.created = None
        self.deleted = None
        self.exists = False

    def create_namespaced_custom_object(self, **kwargs):
        self.created = kwargs
        self.exists = True
        return {"metadata": {"name": kwargs["body"]["metadata"]["name"], "uid": "uid-1"}}

    def delete_namespaced_custom_object(self, **kwargs):
        self.deleted = kwargs
        self.exists = False

    def get_namespaced_custom_object(self, **kwargs):
        if not self.exists:
            raise ApiException(status=404)
        return {"metadata": {"name": kwargs["name"]}, "status": {}}


def manifest():
    return build_podchaos_manifest(
        run_id="run-123",
        environment="staging",
        namespace="platformiq-staging",
        service_name="payment-service",
        operator_id="operator-1",
        deadline="2026-08-02T10:01:00Z",
        duration_seconds=60,
    )


def test_correct_chaos_mesh_manifest_is_sent_to_kubernetes():
    api = RecordingApi()
    result = ChaosMeshAdapter(api=api).inject_fault(
        namespace="platformiq-staging",
        manifest=manifest(),
    )

    assert api.created["group"] == "chaos-mesh.org"
    assert api.created["version"] == "v1alpha1"
    assert api.created["plural"] == "podchaos"
    assert api.created["body"]["spec"]["selector"]["labelSelectors"] == {
        "app.kubernetes.io/name": "payment-service"
    }
    assert result["resource_kind"] == "PodChaos"
    assert result["resource_name"] == "platformiq-run-123"


def test_cleanup_deletes_the_generated_resource():
    api = RecordingApi()
    adapter = ChaosMeshAdapter(api=api)
    result = adapter.inject_fault(
        namespace="platformiq-staging", manifest=manifest()
    )
    adapter.remove_fault(
        resource_kind=result["resource_kind"],
        resource_name=result["resource_name"],
        namespace=result["namespace"],
    )

    assert api.deleted["plural"] == "podchaos"
    assert api.deleted["name"] == "platformiq-run-123"
    assert adapter.verify_cleanup(
        resource_kind=result["resource_kind"],
        resource_name=result["resource_name"],
        namespace=result["namespace"],
    )


def test_mock_adapter_output_is_deterministic():
    first = MockChaosAdapter().inject_fault(
        namespace="platformiq-staging", manifest=manifest()
    )
    second = MockChaosAdapter().inject_fault(
        namespace="platformiq-staging", manifest=manifest()
    )

    assert first == second
    assert first["status"] == "INJECTED"
    assert first["injected_at"] == "2026-08-02T10:00:00Z"


@pytest.fixture
def chaos_db():
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
    db = sessionmaker(bind=engine)()
    user = User(
        id="operator-1",
        email="adapter-test@example.com",
        password_hash="unused",
        full_name="Adapter Test",
        is_active=True,
    )
    project = Project(id="project-1", name="Adapter Project", created_by=user.id)
    service = Service(
        id="service-1",
        project_id=project.id,
        name="payment-service",
        service_type="BACKEND",
        owner="platform-team",
    )
    db.add_all([user, project, service])
    db.flush()
    repository.create_experiment(
        db,
        name="Kill payment pod",
        scenario_type=ChaosScenarioType.POD_KILL,
        target_service_id=service.id,
        target_environment="staging",
        target_namespace="platformiq-staging",
        failure_type="POD_KILL",
        failure_config={},
        expected_behavior={},
        created_by=user.id,
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine, tables=reversed(tables))
        engine.dispose()


def settings():
    return ChaosSettings(
        enabled=True,
        allowed_environments=frozenset({"staging"}),
        allowed_namespaces=frozenset({"platformiq-staging"}),
        allowed_services=frozenset({"payment-service"}),
        max_duration_seconds=600,
        max_concurrent_runs=1,
        watchdog_interval_seconds=30,
        adapter_backend="mock",
    )


def request():
    return ChaosRunCreateRequest.model_validate(
        {
            "environment": "staging",
            "namespace": "platformiq-staging",
            "service": "payment-service",
            "durationSeconds": 30,
            "cleanupBehavior": "delete",
        }
    )


def test_fault_injection_result_is_recorded_and_cleaned_up(chaos_db):
    adapter = MockChaosAdapter()
    run = create_chaos_run(
        db=chaos_db,
        request=request(),
        operator_id="operator-1",
        adapter=adapter,
        settings=settings(),
    )

    observations = repository.list_observations_for_run(chaos_db, run.id)
    assert run.status == ChaosRunStatus.FAULT_INJECTED
    assert run.kubernetes_resource_kind == "PodChaos"
    assert run.kubernetes_resource_name
    assert observations[0].observation_type == ChaosObservationType.FAILURE_INJECTED
    assert observations[0].resource_id == run.kubernetes_resource_name

    cleaned = cleanup_chaos_run(
        db=chaos_db,
        chaos_run=run,
        adapter=adapter,
        reason="test complete",
        aborted=False,
    )
    assert cleaned.cleanup_succeeded is True
    assert adapter.verify_cleanup(
        resource_kind=run.kubernetes_resource_kind,
        resource_name=run.kubernetes_resource_name,
        namespace=run.target_namespace,
    )


class FailingAdapter(MockChaosAdapter):
    def inject_fault(self, *, namespace, manifest):
        raise ChaosKubernetesError("deterministic injection failure")


def test_adapter_failure_marks_run_failed(chaos_db):
    with pytest.raises(ChaosKubernetesError):
        create_chaos_run(
            db=chaos_db,
            request=request(),
            operator_id="operator-1",
            adapter=FailingAdapter(),
            settings=settings(),
        )

    runs = repository.list_active_runs(chaos_db)
    assert runs == []
    failed = chaos_db.query(ChaosRun).one()
    assert failed.status == ChaosRunStatus.FAILED
    assert "deterministic injection failure" in failed.failure_message