"""Validated chaos execution and cleanup orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.chaos import repository
from app.chaos.config import ChaosSettings
from app.chaos.exceptions import (
    ChaosConflictError,
    ChaosDisabledError,
    ChaosExperimentNotFoundError,
    ChaosKubernetesError,
    ChaosRunNotFoundError,
    ChaosValidationError,
)
from app.chaos.adapters.base import BaseChaosAdapter, FaultInjectionResult
from app.chaos.events import CHAOS_OBSERVATION_SOURCE
from app.chaos.kubernetes_adapter import build_podchaos_manifest
from app.chaos.schemas import ChaosRunCreateRequest
from app.models import (
    ChaosExperiment,
    ChaosObservationType,
    ChaosRun,
    ChaosRunStatus,
    ChaosScenarioType,
    Service,
)


def _inject_fault(
    adapter: BaseChaosAdapter,
    *,
    namespace: str,
    manifest: dict,
) -> FaultInjectionResult:
    """Call the 10C contract, accepting 10B test doubles temporarily."""
    if hasattr(adapter, "inject_fault"):
        return adapter.inject_fault(namespace=namespace, manifest=manifest)
    resource = adapter.create_podchaos(  # type: ignore[attr-defined]
        namespace=namespace,
        manifest=manifest,
    )
    return {
        "resource_kind": resource.kind,
        "resource_name": resource.name,
        "namespace": namespace,
        "status": "INJECTED",
        "injected_at": datetime.now(timezone.utc).isoformat(),
        "resource_uid": resource.uid,
    }


def _injected_at(resource: FaultInjectionResult) -> datetime:
    raw = resource.get("injected_at")
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _validate_request(
    request: ChaosRunCreateRequest,
    settings: ChaosSettings,
) -> None:
    if not settings.enabled:
        raise ChaosDisabledError("Chaos execution is disabled")
    if request.environment == "production":
        raise ChaosValidationError("Production chaos is forbidden")
    if request.environment not in settings.allowed_environments:
        raise ChaosValidationError("Environment is not allowlisted")
    if request.namespace not in settings.allowed_namespaces:
        raise ChaosValidationError("Namespace is not allowlisted")
    expected_namespace = settings.environment_namespace_map.get(
        request.environment
    )
    if expected_namespace != request.namespace:
        raise ChaosValidationError(
            "Environment does not map to the requested namespace"
        )
    if request.service not in settings.allowed_services:
        raise ChaosValidationError("Service is not allowlisted")
    if request.duration_seconds > settings.max_duration_seconds:
        raise ChaosValidationError(
            "Duration exceeds CHAOS_MAX_DURATION_SECONDS"
        )
    if request.cleanup_behavior != "delete":
        raise ChaosValidationError("Cleanup behavior must be delete")


def _resolve_experiment(
    db: Session,
    request: ChaosRunCreateRequest,
) -> ChaosExperiment:
    statement = (
        select(ChaosExperiment)
        .join(Service, Service.id == ChaosExperiment.target_service_id)
        .where(
            Service.name == request.service,
            ChaosExperiment.target_environment == request.environment,
            ChaosExperiment.target_namespace == request.namespace,
            ChaosExperiment.scenario_type == ChaosScenarioType.POD_KILL,
            ChaosExperiment.enabled.is_(True),
        )
        .order_by(ChaosExperiment.created_at.desc())
        .limit(1)
    )
    experiment = db.execute(statement).scalar_one_or_none()
    if experiment is None:
        raise ChaosExperimentNotFoundError(
            "No enabled PodKill experiment matches this target"
        )
    return experiment


def create_chaos_run(
    *,
    db: Session,
    request: ChaosRunCreateRequest,
    operator_id: str,
    adapter: BaseChaosAdapter,
    settings: ChaosSettings,
) -> ChaosRun:
    _validate_request(request, settings)
    experiment = _resolve_experiment(db, request)
    started_at = datetime.now(timezone.utc)
    deadline_at = started_at + timedelta(
        seconds=request.duration_seconds
    )

    try:
        chaos_run = repository.create_run(
            db,
            experiment_id=experiment.id,
            triggered_by=operator_id,
            status=ChaosRunStatus.PENDING,
            started_at=started_at,
            duration_seconds=request.duration_seconds,
            cleanup_behavior=request.cleanup_behavior,
            deadline_at=deadline_at,
        )
        db.commit()
        db.refresh(chaos_run)
    except IntegrityError as exc:
        db.rollback()
        raise ChaosConflictError(
            "Another chaos experiment is already active"
        ) from exc

    manifest = build_podchaos_manifest(
        run_id=str(chaos_run.id),
        environment=request.environment,
        namespace=request.namespace,
        service_name=request.service,
        operator_id=operator_id,
        deadline=deadline_at.isoformat(),
        duration_seconds=request.duration_seconds,
    )
    try:
        resource = _inject_fault(
            adapter,
            namespace=request.namespace,
            manifest=manifest,
        )
    except Exception as exc:
        stored_run = repository.get_run_by_id(
            db, chaos_run.id, for_update=True
        )
        if stored_run is not None:
            repository.update_run(
                db,
                chaos_run=stored_run,
                status=ChaosRunStatus.FAILED,
                failure_message=str(exc),
            )
            db.commit()
        if isinstance(exc, ChaosKubernetesError):
            raise
        raise ChaosKubernetesError(
            "Unexpected Kubernetes client failure"
        ) from exc

    stored_run = repository.get_run_by_id(
        db, chaos_run.id, for_update=True
    )
    if stored_run is None:
        raise ChaosRunNotFoundError("Chaos run disappeared after creation")
    injected_at = _injected_at(resource)
    repository.update_run(
        db,
        chaos_run=stored_run,
        status=ChaosRunStatus.FAULT_INJECTED,
        failure_injected_at=injected_at,
        kubernetes_resource_kind=resource["resource_kind"],
        kubernetes_resource_name=resource["resource_name"],
        kubernetes_resource_uid=resource.get("resource_uid"),
    )
    repository.create_observation(
        db,
        chaos_run_id=stored_run.id,
        observation_type=ChaosObservationType.FAILURE_INJECTED,
        source=CHAOS_OBSERVATION_SOURCE,
        observed_at=injected_at,
        resource_type=resource["resource_kind"],
        resource_id=resource["resource_name"],
        details=dict(resource),
    )
    db.commit()
    db.refresh(stored_run)
    return stored_run


def cleanup_chaos_run(
    *,
    db: Session,
    chaos_run: ChaosRun,
    adapter: BaseChaosAdapter,
    reason: str,
    aborted: bool,
    final_status: ChaosRunStatus | None = None,
) -> ChaosRun:
    terminal_statuses = {
        ChaosRunStatus.COMPLETED,
        ChaosRunStatus.ABORTED,
        ChaosRunStatus.FAILED,
    }
    if (
        chaos_run.status in terminal_statuses
        and chaos_run.cleanup_succeeded is True
    ):
        return chaos_run

    now = datetime.now(timezone.utc)
    repository.update_run(
        db,
        chaos_run=chaos_run,
        status=ChaosRunStatus.RECOVERING,
        cleanup_started_at=now,
        cleanup_error=None,
    )
    db.commit()
    try:
        if chaos_run.kubernetes_resource_name:
            resource_kind = (
                chaos_run.kubernetes_resource_kind or "PodChaos"
            )
            adapter.remove_fault(
                resource_kind=resource_kind,
                namespace=chaos_run.target_namespace,
                resource_name=chaos_run.kubernetes_resource_name,
            )
            if not adapter.verify_cleanup(
                resource_kind=resource_kind,
                namespace=chaos_run.target_namespace,
                resource_name=chaos_run.kubernetes_resource_name,
            ):
                raise ChaosKubernetesError(
                    "Timed out waiting for Chaos Mesh resource deletion"
                )
    except Exception as exc:
        stored = repository.get_run_by_id(
            db, chaos_run.id, for_update=True
        )
        if stored is not None:
            repository.update_run(
                db,
                chaos_run=stored,
                cleanup_succeeded=False,
                cleanup_error=str(exc),
                failure_message=reason,
            )
            db.commit()
        if isinstance(exc, ChaosKubernetesError):
            raise
        raise ChaosKubernetesError("Chaos cleanup failed") from exc

    stored = repository.get_run_by_id(
        db, chaos_run.id, for_update=True
    )
    if stored is None:
        raise ChaosRunNotFoundError("Chaos run was not found")
    completed_at = datetime.now(timezone.utc)

    resolved_status = final_status or (
        ChaosRunStatus.ABORTED
        if aborted
        else ChaosRunStatus.COMPLETED
    )

    if resolved_status not in terminal_statuses:
        raise ValueError("final_status must be terminal")

    values = {
        "status": resolved_status,
        "cleanup_completed_at": completed_at,
        "cleanup_succeeded": True,
        "cleanup_error": None,
        "failure_message": (
            None
            if resolved_status == ChaosRunStatus.COMPLETED
            else reason
        ),
    }

    if resolved_status == ChaosRunStatus.ABORTED:
        values["aborted_at"] = completed_at
    elif resolved_status == ChaosRunStatus.COMPLETED:
        values["completed_at"] = completed_at

    repository.update_run(
        db,
        chaos_run=stored,
        **values,
    )
    db.commit()
    db.refresh(stored)
    return stored


def get_run_or_raise(db: Session, run_id: UUID) -> ChaosRun:
    run = repository.get_run_by_id(db, run_id)
    if run is None:
        raise ChaosRunNotFoundError("Chaos run was not found")
    return run