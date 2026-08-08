from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.chaos import repository
from app.database import Base
from app.models import (
    BenchmarkStatus,
    ChaosExperiment,
    ChaosObservationType,
    ChaosRun,
    ChaosRunStatus,
    ChaosScenarioType,
    DiagnosisRating,
    ExperimentBenchmark,
    Project,
    Service,
    User,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        User.__table__,
        Project.__table__,
        Service.__table__,
        ChaosExperiment.__table__,
        ChaosRun.__table__,
        repository.ChaosObservation.__table__,
        ExperimentBenchmark.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    session = sessionmaker(bind=engine)()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine, tables=reversed(tables))
        engine.dispose()


def create_chaos_context(db_session):
    user = User(
        id=str(uuid4()),
        email=f"sprint10a-{uuid4()}@example.com",
        password_hash="test-password-hash",
        full_name="Sprint 10A Operator",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    project = Project(
        id=str(uuid4()),
        name=f"Sprint 10A Project {uuid4()}",
        created_by=user.id,
    )
    db_session.add(project)
    db_session.flush()

    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name=f"checkout-service-{uuid4()}",
        service_type="BACKEND",
        owner="platform-team",
    )
    db_session.add(service)
    db_session.flush()

    experiment = repository.create_experiment(
        db_session,
        name="Kill one checkout pod",
        description="Validate redundant checkout capacity.",
        scenario_type=ChaosScenarioType.POD_KILL,
        target_service_id=service.id,
        target_environment="staging",
        target_namespace="platformiq-demo",
        failure_type="KUBERNETES_POD_DELETE",
        failure_config={"pod_selector": "app=checkout"},
        expected_behavior={"availability_min": 0.99},
        created_by=user.id,
    )

    return {
        "user": user,
        "project": project,
        "service": service,
        "experiment": experiment,
    }


def test_chaos_enum_contracts_are_complete():
    assert {member.value for member in ChaosScenarioType} == {
        "FAULTY_RELEASE",
        "POD_KILL",
        "NETWORK_DELAY",
        "DATABASE_DELAY",
        "CPU_PRESSURE",
    }
    assert {member.value for member in ChaosRunStatus} == {
        "PENDING",
        "RUNNING",
        "FAULT_INJECTED",
        "OBSERVING",
        "RECOVERING",
        "COMPLETED",
        "FAILED",
        "ABORTED",
    }
    assert {member.value for member in ChaosObservationType} == {
        "FAILURE_INJECTED",
        "TELEMETRY_ANOMALY",
        "ALERT_CREATED",
        "INCIDENT_CREATED",
        "RCA_COMPLETED",
        "REMEDIATION_RECOMMENDED",
        "REMEDIATION_APPROVED",
        "REMEDIATION_EXECUTED",
        "RECOVERY_COMPLETED",
    }


def test_experiment_repository_persists_and_filters(db_session):
    context = create_chaos_context(db_session)
    experiment = context["experiment"]

    db_session.commit()
    db_session.expire_all()

    stored = repository.get_experiment_by_id(db_session, experiment.id)
    matching = repository.list_experiments(
        db_session,
        target_service_id=context["service"].id,
        target_environment="staging",
        scenario_type=ChaosScenarioType.POD_KILL,
        enabled=True,
    )

    assert stored is not None
    assert stored.failure_config == {"pod_selector": "app=checkout"}
    assert stored.expected_behavior == {"availability_min": 0.99}
    assert stored.target_service.id == context["service"].id
    assert stored.creator.id == context["user"].id
    assert [item.id for item in matching] == [experiment.id]


def test_run_observations_and_benchmark_relationships(db_session):
    context = create_chaos_context(db_session)
    now = datetime.now(timezone.utc)
    chaos_run = repository.create_run(
        db_session,
        experiment_id=context["experiment"].id,
        triggered_by=context["user"].id,
        status=ChaosRunStatus.RUNNING,
        started_at=now,
    )
    later = now + timedelta(seconds=2)
    repository.create_observation(
        db_session,
        chaos_run_id=chaos_run.id,
        observation_type=ChaosObservationType.TELEMETRY_ANOMALY,
        source="prometheus",
        observed_at=later,
        resource_type="Deployment",
        resource_id="checkout-service",
        details={"error_rate": 0.08},
    )
    repository.create_observation(
        db_session,
        chaos_run_id=chaos_run.id,
        observation_type=ChaosObservationType.FAILURE_INJECTED,
        source="chaos-runner",
        observed_at=now,
        details={"pod": "checkout-abc"},
    )
    benchmark = repository.save_benchmark(
        db_session,
        chaos_run_id=chaos_run.id,
        values={
            "failure_injection_timestamp": now,
            "first_anomaly_timestamp": later,
            "time_to_detect_ms": 2000,
            "diagnosis_rating": DiagnosisRating.CORRECT,
            "detection_succeeded": True,
            "benchmark_status": BenchmarkStatus.PASSED,
        },
    )
    db_session.commit()
    db_session.expire_all()

    stored_run = repository.get_run_by_id(db_session, chaos_run.id)
    observations = repository.list_observations_for_run(
        db_session,
        chaos_run.id,
    )

    assert stored_run.experiment.id == context["experiment"].id
    assert stored_run.trigger_user.id == context["user"].id
    assert [item.observation_type for item in observations] == [
        ChaosObservationType.FAILURE_INJECTED,
        ChaosObservationType.TELEMETRY_ANOMALY,
    ]
    assert stored_run.benchmark.id == benchmark.id
    assert stored_run.benchmark.time_to_detect_ms == 2000
    assert stored_run.benchmark.diagnosis_rating == DiagnosisRating.CORRECT


def test_save_benchmark_updates_the_single_run_benchmark(db_session):
    context = create_chaos_context(db_session)
    chaos_run = repository.create_run(
        db_session,
        experiment_id=context["experiment"].id,
    )
    first = repository.save_benchmark(
        db_session,
        chaos_run_id=chaos_run.id,
        values={"time_to_detect_ms": 1000},
    )
    second = repository.save_benchmark(
        db_session,
        chaos_run_id=chaos_run.id,
        values={
            "time_to_detect_ms": 750,
            "benchmark_status": BenchmarkStatus.PASSED,
        },
    )

    assert first.id == second.id
    assert second.time_to_detect_ms == 750
    assert second.benchmark_status == BenchmarkStatus.PASSED


def test_artifact_links_can_be_added_progressively(db_session):
    context = create_chaos_context(db_session)
    chaos_run = repository.create_run(
        db_session,
        experiment_id=context["experiment"].id,
    )
    incident_id = uuid4()
    rca_report_id = uuid4()

    repository.link_run_artifacts(
        db_session,
        chaos_run=chaos_run,
        incident_id=incident_id,
    )
    repository.link_run_artifacts(
        db_session,
        chaos_run=chaos_run,
        rca_report_id=rca_report_id,
    )

    assert chaos_run.incident_id == incident_id
    assert chaos_run.rca_report_id == rca_report_id


def test_save_benchmark_rejects_unknown_fields(db_session):
    context = create_chaos_context(db_session)
    chaos_run = repository.create_run(
        db_session,
        experiment_id=context["experiment"].id,
    )

    with pytest.raises(ValueError, match="Unsupported benchmark fields"):
        repository.save_benchmark(
            db_session,
            chaos_run_id=chaos_run.id,
            values={"not_a_benchmark_field": 1},
        )


def test_only_one_benchmark_is_allowed_per_run(db_session):
    context = create_chaos_context(db_session)
    chaos_run = repository.create_run(
        db_session,
        experiment_id=context["experiment"].id,
    )
    db_session.add_all(
        [
            ExperimentBenchmark(chaos_run_id=chaos_run.id),
            ExperimentBenchmark(chaos_run_id=chaos_run.id),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_benchmark_durations_cannot_be_negative(db_session):
    context = create_chaos_context(db_session)
    chaos_run = repository.create_run(
        db_session,
        experiment_id=context["experiment"].id,
    )
    db_session.add(
        ExperimentBenchmark(
            chaos_run_id=chaos_run.id,
            time_to_recover_ms=-1,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_deleting_experiment_cascades_owned_run_data(db_session):
    context = create_chaos_context(db_session)
    chaos_run = repository.create_run(
        db_session,
        experiment_id=context["experiment"].id,
    )
    repository.create_observation(
        db_session,
        chaos_run_id=chaos_run.id,
        observation_type=ChaosObservationType.FAILURE_INJECTED,
        source="chaos-runner",
        observed_at=datetime.now(timezone.utc),
        details={},
    )
    repository.save_benchmark(
        db_session,
        chaos_run_id=chaos_run.id,
        values={},
    )
    run_id = chaos_run.id

    db_session.delete(context["experiment"])
    db_session.commit()

    assert db_session.get(ChaosExperiment, context["experiment"].id) is None
    assert db_session.get(ChaosRun, run_id) is None