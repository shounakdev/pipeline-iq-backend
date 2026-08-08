from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.chaos import repository
from app.chaos.adapters.mock_adapter import MockChaosAdapter
from app.chaos.config import ChaosSettings
from app.chaos.router import start_chaos_run
from app.chaos.schemas import ChaosRunCreateRequest
from app.chaos.services.experiment_service import create_pending_run
from app.chaos.services.run_service import ObservationResult, execute_run
from app.database import Base
from app.models import (
    ChaosExperiment,
    ChaosObservation,
    ChaosRun,
    ChaosRunStatus,
    ChaosScenarioType,
    ExperimentBenchmark,
    Project,
    Service,
    User,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


@pytest.fixture
def orchestration_db():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        User.__table__,
        Project.__table__,
        Service.__table__,
        ChaosExperiment.__table__,
        ChaosRun.__table__,
        ChaosObservation.__table__,
        ExperimentBenchmark.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    db = sessionmaker(bind=engine)()
    user = User(
        id="operator-1",
        email="operator@example.com",
        password_hash="unused",
        full_name="Operator",
        is_active=True,
    )
    project = Project(id="project-1", name="Chaos", created_by=user.id)
    service = Service(
        id="service-1",
        project_id=project.id,
        name="chaos-test-service",
        service_type="BACKEND",
    )
    db.add_all([user, project, service])
    db.flush()
    repository.create_experiment(
        db,
        name="Kill a pod",
        scenario_type=ChaosScenarioType.POD_KILL,
        target_service_id=service.id,
        target_environment="development",
        target_namespace="platformiq-dev",
        failure_type="POD_KILL",
        failure_config={},
        expected_behavior={},
        created_by=user.id,
    )
    db.commit()
    try:
        yield db, user
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine, tables=reversed(tables))
        engine.dispose()


def settings() -> ChaosSettings:
    return ChaosSettings(
        enabled=True,
        allowed_environments=frozenset({"development"}),
        allowed_namespaces=frozenset({"platformiq-dev"}),
        allowed_services=frozenset({"chaos-test-service"}),
        max_duration_seconds=600,
        max_concurrent_runs=1,
        watchdog_interval_seconds=1,
        adapter_backend="mock",
    )


def request() -> ChaosRunCreateRequest:
    return ChaosRunCreateRequest.model_validate({
        "environment": "development",
        "namespace": "platformiq-dev",
        "service": "chaos-test-service",
        "durationSeconds": 2,
        "cleanupBehavior": "delete",
    })


class RecoveredObserver:
    def capture_baseline(self, db, run):
        return {"status": "HEALTHY"}

    def observe(self, db, run, baseline):
        repository.create_observation(
            db,
            chaos_run_id=run.id,
            observation_type=repository.ChaosObservationType.RECOVERY_COMPLETED,
            source="test",
            observed_at=datetime.now(timezone.utc),
            resource_type="test",
            resource_id="recovery-1",
            details=baseline,
        )
        db.commit()
        return ObservationResult(recovered=True)


class FailingObserver:
    def capture_baseline(self, db, run):
        return {}

    def observe(self, db, run, baseline):
        raise RuntimeError("observer failed")


class NeverRecoveredObserver:
    def capture_baseline(self, db, run):
        return {}

    def observe(self, db, run, baseline):
        return ObservationResult()


class TrackingAdapter(MockChaosAdapter):
    def __init__(self):
        super().__init__()
        self.remove_calls = 0

    def remove_fault(self, **kwargs):
        self.remove_calls += 1
        return super().remove_fault(**kwargs)


class FailingAdapter(TrackingAdapter):
    def inject_fault(self, **kwargs):
        raise RuntimeError("adapter failed")


def pending_run(db):
    return create_pending_run(
        db=db,
        request=request(),
        operator_id="operator-1",
        settings=settings(),
    )


def test_run_created_successfully_as_pending(orchestration_db):
    db, _ = orchestration_db
    run = pending_run(db)
    assert run.status == ChaosRunStatus.PENDING
    assert run.failure_injected_at is None


def test_background_execution_starts(orchestration_db, monkeypatch):
    db, user = orchestration_db
    queued = []
    monkeypatch.setattr(
        "app.chaos.router.execute_chaos_run.delay",
        lambda run_id: queued.append(run_id),
    )
    run = start_chaos_run(request(), db, user, settings())
    assert run.status == ChaosRunStatus.PENDING
    assert queued == [str(run.id)]


def test_injection_timestamp_and_cleanup_are_recorded(orchestration_db):
    db, _ = orchestration_db
    run = pending_run(db)
    adapter = TrackingAdapter()
    completed = execute_run(
        db=db,
        chaos_run_id=run.id,
        adapter=adapter,
        observer=RecoveredObserver(),
    )
    assert completed.status == ChaosRunStatus.COMPLETED
    assert completed.failure_injected_at is not None
    assert completed.cleanup_succeeded is True
    assert adapter.remove_calls == 1


def test_adapter_or_observer_exception_marks_failed_and_cleans_up(
    orchestration_db,
):
    db, _ = orchestration_db
    run = pending_run(db)
    adapter = TrackingAdapter()
    failed = execute_run(
        db=db,
        chaos_run_id=run.id,
        adapter=adapter,
        observer=FailingObserver(),
    )
    assert failed.status == ChaosRunStatus.FAILED
    assert "observer failed" in failed.failure_message
    assert failed.cleanup_succeeded is True
    assert adapter.remove_calls == 1


def test_adapter_exception_marks_run_failed(orchestration_db):
    db, _ = orchestration_db
    run = pending_run(db)
    adapter = FailingAdapter()
    failed = execute_run(
        db=db,
        chaos_run_id=run.id,
        adapter=adapter,
        observer=NeverRecoveredObserver(),
    )
    assert failed.status == ChaosRunStatus.FAILED
    assert "adapter failed" in failed.failure_message
    assert failed.cleanup_succeeded is True
    assert adapter.remove_calls == 1


def test_timeout_marks_failed_and_cleans_up(orchestration_db):
    db, _ = orchestration_db
    run = pending_run(db)
    adapter = TrackingAdapter()
    elapsed = [0.0]

    def sleep(seconds):
        elapsed[0] += seconds

    failed = execute_run(
        db=db,
        chaos_run_id=run.id,
        adapter=adapter,
        observer=NeverRecoveredObserver(),
        timeout_seconds=2,
        monotonic=lambda: elapsed[0],
        sleeper=sleep,
    )
    assert failed.status == ChaosRunStatus.FAILED
    assert "not observed" in failed.failure_message
    assert failed.cleanup_succeeded is True
    assert adapter.remove_calls == 1