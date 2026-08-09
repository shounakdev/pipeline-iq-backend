from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BenchmarkStatus,
    ChaosExperiment,
    ChaosObservation,
    ChaosObservationType,
    ChaosRun,
    ChaosRunStatus,
    ChaosScenarioType,
    ExperimentBenchmark,
)


BENCHMARK_MUTABLE_FIELDS = {
    "failure_injection_timestamp",
    "first_anomaly_timestamp",
    "alert_creation_timestamp",
    "incident_creation_timestamp",
    "rca_completion_timestamp",
    "remediation_approval_timestamp",
    "recovery_completion_timestamp",
    "time_to_detect_ms",
    "time_to_alert_ms",
    "time_to_incident_ms",
    "time_to_diagnose_ms",
    "time_to_approve_ms",
    "time_to_recover_ms",
    "diagnosis_rating",
    "expected_root_cause",
    "actual_root_cause",
    "detection_succeeded",
    "recovery_succeeded",
    "benchmark_status",
    "calculated_at",
}

_UNSET = object()


def create_experiment(
    db: Session,
    *,
    name: str,
    scenario_type: ChaosScenarioType,
    target_service_id: str,
    target_environment: str,
    target_namespace: str,
    failure_type: str,
    failure_config: dict[str, Any],
    expected_behavior: dict[str, Any],
    description: str | None = None,
    enabled: bool = True,
    created_by: str | None = None,
) -> ChaosExperiment:
    experiment = ChaosExperiment(
        name=name,
        description=description,
        scenario_type=scenario_type,
        target_service_id=target_service_id,
        target_environment=target_environment,
        target_namespace=target_namespace,
        failure_type=failure_type,
        failure_config=failure_config,
        expected_behavior=expected_behavior,
        enabled=enabled,
        created_by=created_by,
    )
    db.add(experiment)
    db.flush()
    db.refresh(experiment)
    return experiment


def get_experiment_by_id(
    db: Session,
    experiment_id: UUID,
    *,
    for_update: bool = False,
) -> ChaosExperiment | None:
    statement = select(ChaosExperiment).where(
        ChaosExperiment.id == experiment_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.execute(statement).scalar_one_or_none()


def list_experiments(
    db: Session,
    *,
    target_service_id: str | None = None,
    target_environment: str | None = None,
    scenario_type: ChaosScenarioType | None = None,
    enabled: bool | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[ChaosExperiment]:
    statement = select(ChaosExperiment)
    if target_service_id is not None:
        statement = statement.where(
            ChaosExperiment.target_service_id == target_service_id,
        )
    if target_environment is not None:
        statement = statement.where(
            ChaosExperiment.target_environment == target_environment,
        )
    if scenario_type is not None:
        statement = statement.where(
            ChaosExperiment.scenario_type == scenario_type,
        )
    if enabled is not None:
        statement = statement.where(ChaosExperiment.enabled.is_(enabled))
    statement = (
        statement.order_by(
            ChaosExperiment.created_at.desc(),
            ChaosExperiment.id.desc(),
        )
        .offset(max(offset, 0))
        .limit(max(limit, 0))
    )
    return list(db.scalars(statement).all())


def create_run(
    db: Session,
    *,
    experiment_id: UUID,
    triggered_by: str | None = None,
    status: ChaosRunStatus = ChaosRunStatus.PENDING,
    started_at: datetime | None = None,
    duration_seconds: int = 600,
    cleanup_behavior: str = "delete",
    deadline_at: datetime | None = None,
) -> ChaosRun:
    experiment = get_experiment_by_id(db, experiment_id)
    if experiment is None:
        raise ValueError("Chaos experiment was not found")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")
    if cleanup_behavior != "delete":
        raise ValueError("cleanup_behavior must be 'delete'")

    effective_started_at = started_at or datetime.now(timezone.utc)
    effective_deadline = deadline_at or (
        effective_started_at + timedelta(seconds=duration_seconds)
    )
    chaos_run = ChaosRun(
        experiment_id=experiment_id,
        triggered_by=triggered_by,
        status=status,
        started_at=effective_started_at,
        target_environment=experiment.target_environment,
        target_service_id=experiment.target_service_id,
        target_namespace=experiment.target_namespace,
        duration_seconds=duration_seconds,
        cleanup_behavior=cleanup_behavior,
        deadline_at=effective_deadline,
    )
    db.add(chaos_run)
    db.flush()
    db.refresh(chaos_run)
    return chaos_run


def list_active_runs(
    db: Session,
    *,
    deadline_before: datetime | None = None,
    for_update: bool = False,
) -> list[ChaosRun]:
    active_statuses = (
        ChaosRunStatus.PENDING,
        ChaosRunStatus.RUNNING,
        ChaosRunStatus.FAULT_INJECTED,
        ChaosRunStatus.OBSERVING,
        ChaosRunStatus.RECOVERING,
    )
    statement = select(ChaosRun).where(
        ChaosRun.status.in_(active_statuses),
    )
    if deadline_before is not None:
        statement = statement.where(
            ChaosRun.deadline_at <= deadline_before,
        )
    if for_update:
        statement = statement.with_for_update(skip_locked=True)
    statement = statement.order_by(
        ChaosRun.deadline_at.asc(),
        ChaosRun.id.asc(),
    )
    return list(db.scalars(statement).all())


def update_run(
    db: Session,
    *,
    chaos_run: ChaosRun,
    **values: Any,
) -> ChaosRun:
    allowed_fields = {
        "status",
        "failure_injected_at",
        "completed_at",
        "aborted_at",
        "failure_message",
        "kubernetes_resource_kind",
        "kubernetes_resource_name",
        "kubernetes_resource_uid",
        "cleanup_started_at",
        "cleanup_completed_at",
        "cleanup_succeeded",
        "cleanup_error",
    }
    unknown_fields = set(values) - allowed_fields
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unsupported chaos run fields: {names}")
    for field, value in values.items():
        setattr(chaos_run, field, value)
    db.flush()
    db.refresh(chaos_run)
    return chaos_run


def get_run_by_id(
    db: Session,
    chaos_run_id: UUID,
    *,
    for_update: bool = False,
) -> ChaosRun | None:
    statement = select(ChaosRun).where(ChaosRun.id == chaos_run_id)
    if for_update:
        statement = statement.with_for_update()
    return db.execute(statement).scalar_one_or_none()


def list_runs_for_experiment(
    db: Session,
    experiment_id: UUID,
    *,
    status: ChaosRunStatus | None = None,
    limit: int = 100,
) -> list[ChaosRun]:
    statement = select(ChaosRun).where(
        ChaosRun.experiment_id == experiment_id,
    )
    if status is not None:
        statement = statement.where(ChaosRun.status == status)
    statement = statement.order_by(
        ChaosRun.started_at.desc().nullslast(),
        ChaosRun.id.desc(),
    ).limit(max(limit, 0))
    return list(db.scalars(statement).all())


def link_run_artifacts(
    db: Session,
    *,
    chaos_run: ChaosRun,
    incident_id: UUID | None | object = _UNSET,
    rca_report_id: UUID | None | object = _UNSET,
    remediation_id: UUID | None | object = _UNSET,
    remediation_execution_id: UUID | None | object = _UNSET,
    recovery_verification_id: UUID | None | object = _UNSET,
) -> ChaosRun:
    artifact_values = {
        "incident_id": incident_id,
        "rca_report_id": rca_report_id,
        "remediation_id": remediation_id,
        "remediation_execution_id": remediation_execution_id,
        "recovery_verification_id": recovery_verification_id,
    }
    for field, value in artifact_values.items():
        if value is not _UNSET:
            setattr(chaos_run, field, value)
    db.flush()
    db.refresh(chaos_run)
    return chaos_run


def create_observation(
    db: Session,
    *,
    chaos_run_id: UUID,
    observation_type: ChaosObservationType,
    source: str,
    details: dict[str, Any],
    observed_at: datetime,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> ChaosObservation:
    observation = ChaosObservation(
        chaos_run_id=chaos_run_id,
        observation_type=observation_type,
        source=source,
        observed_at=observed_at,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )
    db.add(observation)
    db.flush()
    db.refresh(observation)
    return observation


def list_observations_for_run(
    db: Session,
    chaos_run_id: UUID,
    *,
    observation_type: ChaosObservationType | None = None,
) -> list[ChaosObservation]:
    statement = select(ChaosObservation).where(
        ChaosObservation.chaos_run_id == chaos_run_id,
    )
    if observation_type is not None:
        statement = statement.where(
            ChaosObservation.observation_type == observation_type,
        )
    statement = statement.order_by(
        ChaosObservation.observed_at.asc(),
        ChaosObservation.id.asc(),
    )
    return list(db.scalars(statement).all())


def get_benchmark_for_run(
    db: Session,
    chaos_run_id: UUID,
    *,
    for_update: bool = False,
) -> ExperimentBenchmark | None:
    statement = select(ExperimentBenchmark).where(
        ExperimentBenchmark.chaos_run_id == chaos_run_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.execute(statement).scalar_one_or_none()

def list_benchmarks_for_experiment(
    db: Session,
    experiment_id: UUID,
) -> list[ExperimentBenchmark]:
    """Return experiment benchmarks in chronological order."""
    statement = (
        select(ExperimentBenchmark)
        .join(
            ChaosRun,
            ChaosRun.id
            == ExperimentBenchmark.chaos_run_id,
        )
        .where(
            ChaosRun.experiment_id == experiment_id,
        )
        .order_by(
            ExperimentBenchmark.calculated_at.asc(),
            ExperimentBenchmark.id.asc(),
        )
    )

    return list(db.scalars(statement).all())


def save_benchmark(
    db: Session,
    *,
    chaos_run_id: UUID,
    values: dict[str, Any],
) -> ExperimentBenchmark:
    unknown_fields = set(values) - BENCHMARK_MUTABLE_FIELDS
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unsupported benchmark fields: {names}")

    benchmark = get_benchmark_for_run(
        db,
        chaos_run_id,
        for_update=True,
    )
    if benchmark is None:
        benchmark = ExperimentBenchmark(
            chaos_run_id=chaos_run_id,
            benchmark_status=BenchmarkStatus.INCOMPLETE,
        )
        db.add(benchmark)

    for field, value in values.items():
        setattr(benchmark, field, value)

    db.flush()
    db.refresh(benchmark)
    return benchmark
