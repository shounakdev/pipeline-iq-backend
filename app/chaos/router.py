from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.audit.service import create_audit_event
from app.auth.dependencies import require_roles
from app.chaos import repository
from app.chaos.adapters.chaos_mesh_adapter import ChaosMeshAdapter
from app.chaos.config import ChaosSettings
from app.chaos.exceptions import (
    ChaosConflictError,
    ChaosDisabledError,
    ChaosError,
    ChaosExperimentNotFoundError,
    ChaosKubernetesError,
    ChaosRunNotFoundError,
    ChaosValidationError,
)
from app.chaos.schemas import (
    ChaosCleanupResponse,
    ChaosRunCreateRequest,
    ChaosRunResponse,
    ExperimentBenchmarkResponse,
    ExperimentCreateRequest,
    ExperimentResponse,
    ExperimentRunQueuedResponse,
    ExperimentRunResponse,
)
from app.chaos.events import create_chaos_experiment_created_event
from app.chaos.service import cleanup_chaos_run, get_run_or_raise
from app.chaos.services.experiment_service import (
    create_pending_run,
    create_pending_run_for_experiment,
)
from app.chaos.tasks import execute_chaos_run
from app.database import get_db
from app.models import ChaosRunStatus, Service, User


router = APIRouter(prefix="/api/chaos", tags=["Chaos Engineering"])
experiments_router = APIRouter(
    prefix="/api/experiments",
    tags=["Chaos Experiments"],
)
operator_roles = require_roles("admin", "operator")
read_roles = require_roles("admin", "operator", "developer", "viewer")


def get_chaos_settings() -> ChaosSettings:
    return ChaosSettings.from_env()


def get_chaos_adapter() -> ChaosMeshAdapter:
    return ChaosMeshAdapter()


def _translate_error(exc: ChaosError) -> HTTPException:
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, ChaosDisabledError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, ChaosConflictError):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(
        exc, (ChaosExperimentNotFoundError, ChaosRunNotFoundError)
    ):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, ChaosKubernetesError):
        status_code = status.HTTP_502_BAD_GATEWAY
    elif isinstance(exc, ChaosValidationError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    actor_id: str,
    entity_id: str | None = None,
    details: dict | None = None,
) -> None:
    create_audit_event(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        details=details or {},
    )
    db.commit()


def _experiment_or_404(db: Session, experiment_id: UUID):
    experiment = repository.get_experiment_by_id(db, experiment_id)
    if experiment is None:
        raise _translate_error(
            ChaosExperimentNotFoundError("Chaos experiment was not found")
        )
    return experiment


@experiments_router.post(
    "",
    response_model=ExperimentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_experiment(
    request: ExperimentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(operator_roles),
):
    if request.target_environment.lower() == "production":
        _audit(
            db,
            action="CHAOS_EXPERIMENT_CREATE_FAILED",
            entity_type="ChaosExperiment",
            actor_id=str(current_user.id),
            details={"reason": "Production chaos is forbidden"},
        )
        raise _translate_error(
            ChaosValidationError("Production chaos is forbidden")
        )

    target_service = db.get(Service, request.target_service_id)
    if target_service is None:
        _audit(
            db,
            action="CHAOS_EXPERIMENT_CREATE_FAILED",
            entity_type="ChaosExperiment",
            actor_id=str(current_user.id),
            details={
                "reason": "Target service was not found",
                "target_service_id": request.target_service_id,
            },
        )
        raise _translate_error(
            ChaosValidationError("Target service was not found")
        )

    experiment = repository.create_experiment(
        db,
        name=request.name,
        description=request.description,
        scenario_type=request.scenario_type,
        target_service_id=request.target_service_id,
        target_environment=request.target_environment,
        target_namespace=request.target_namespace,
        failure_type=request.scenario_type.value,
        failure_config=request.failure_config,
        expected_behavior=request.expected_behavior,
        enabled=request.enabled,
        created_by=str(current_user.id),
    )
    create_chaos_experiment_created_event(db=db, experiment=experiment)
    create_audit_event(
        db,
        action="CHAOS_EXPERIMENT_CREATED",
        entity_type="ChaosExperiment",
        entity_id=str(experiment.id),
        actor_id=str(current_user.id),
        details={"scenario_type": request.scenario_type.value},
    )
    db.commit()
    db.refresh(experiment)
    return experiment


@experiments_router.get("", response_model=list[ExperimentResponse])
def get_experiments(
    db: Session = Depends(get_db),
    _current_user: User = Depends(read_roles),
):
    return repository.list_experiments(db)


@experiments_router.get(
    "/runs/{run_id}",
    response_model=ExperimentRunResponse,
)
def get_experiment_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(read_roles),
):
    try:
        return get_run_or_raise(db, run_id)
    except ChaosError as exc:
        raise _translate_error(exc) from exc


@experiments_router.post(
    "/runs/{run_id}/abort",
    response_model=ExperimentRunResponse,
)
def abort_experiment_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(operator_roles),
    adapter: ChaosMeshAdapter = Depends(get_chaos_adapter),
):
    try:
        run = get_run_or_raise(db, run_id)
        aborted = cleanup_chaos_run(
            db=db,
            chaos_run=run,
            adapter=adapter,
            reason="aborted by operator",
            aborted=True,
        )
        _audit(
            db,
            action="CHAOS_RUN_ABORTED",
            entity_type="ChaosRun",
            entity_id=str(aborted.id),
            actor_id=str(current_user.id),
            details={"experiment_id": str(aborted.experiment_id)},
        )
        db.refresh(aborted)
        return aborted
    except ChaosError as exc:
        db.rollback()
        _audit(
            db,
            action="CHAOS_RUN_ABORT_FAILED",
            entity_type="ChaosRun",
            entity_id=str(run_id),
            actor_id=str(current_user.id),
            details={"code": exc.code, "reason": str(exc)},
        )
        raise _translate_error(exc) from exc


@experiments_router.post(
    "/{experiment_id}/run",
    response_model=ExperimentRunQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_experiment(
    experiment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(operator_roles),
    settings: ChaosSettings = Depends(get_chaos_settings),
):
    try:
        experiment = _experiment_or_404(db, experiment_id)
        run = create_pending_run_for_experiment(
            db=db,
            experiment=experiment,
            operator_id=str(current_user.id),
            settings=settings,
        )
        _audit(
            db,
            action="CHAOS_RUN_QUEUED",
            entity_type="ChaosRun",
            entity_id=str(run.id),
            actor_id=str(current_user.id),
            details={"experiment_id": str(experiment.id)},
        )
        try:
            execute_chaos_run.delay(str(run.id))
        except Exception as exc:
            repository.update_run(
                db,
                chaos_run=run,
                status=ChaosRunStatus.FAILED,
                failure_message="Failed to queue chaos experiment",
            )
            _audit(
                db,
                action="CHAOS_RUN_FAILED",
                entity_type="ChaosRun",
                entity_id=str(run.id),
                actor_id=str(current_user.id),
                details={
                    "experiment_id": str(experiment.id),
                    "reason": type(exc).__name__,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chaos experiment could not be queued",
            ) from exc
        return ExperimentRunQueuedResponse(
            run_id=run.id,
            experiment_id=experiment.id,
            status=run.status,
            message="Chaos experiment queued.",
        )
    except HTTPException:
        raise
    except ChaosError as exc:
        db.rollback()
        _audit(
            db,
            action="CHAOS_RUN_REQUEST_FAILED",
            entity_type="ChaosExperiment",
            entity_id=str(experiment_id),
            actor_id=str(current_user.id),
            details={"code": exc.code, "reason": str(exc)},
        )
        raise _translate_error(exc) from exc


@experiments_router.get(
    "/{experiment_id}/runs",
    response_model=list[ExperimentRunResponse],
)
def get_experiment_runs(
    experiment_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(read_roles),
):
    _experiment_or_404(db, experiment_id)
    return repository.list_runs_for_experiment(db, experiment_id)


@experiments_router.get(
    "/{experiment_id}/benchmarks",
    response_model=list[ExperimentBenchmarkResponse],
)
def get_experiment_benchmarks(
    experiment_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(read_roles),
):
    _experiment_or_404(db, experiment_id)
    return repository.list_benchmarks_for_experiment(db, experiment_id)


@experiments_router.get(
    "/{experiment_id}",
    response_model=ExperimentResponse,
)
def get_experiment(
    experiment_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(read_roles),
):
    return _experiment_or_404(db, experiment_id)


@router.post(
    "/runs",
    response_model=ChaosRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_chaos_run(
    request: ChaosRunCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(operator_roles),
    settings: ChaosSettings = Depends(get_chaos_settings),
):
    try:
        run = create_pending_run(
            db=db,
            request=request,
            operator_id=str(current_user.id),
            settings=settings,
        )
        execute_chaos_run.delay(str(run.id))
        return run
    except ChaosError as exc:
        raise _translate_error(exc) from exc


@router.get("/runs/{run_id}", response_model=ChaosRunResponse)
def get_chaos_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(read_roles),
):
    try:
        return get_run_or_raise(db, run_id)
    except ChaosError as exc:
        raise _translate_error(exc) from exc


@router.delete(
    "/runs/{run_id}",
    response_model=ChaosCleanupResponse,
)
def cancel_chaos_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(operator_roles),
    adapter: ChaosMeshAdapter = Depends(get_chaos_adapter),
):
    try:
        run = get_run_or_raise(db, run_id)
        cleaned = cleanup_chaos_run(
            db=db,
            chaos_run=run,
            adapter=adapter,
            reason="cancelled by operator",
            aborted=True,
        )
        return ChaosCleanupResponse(
            run_id=cleaned.id,
            status=cleaned.status,
            cleanup_succeeded=bool(cleaned.cleanup_succeeded),
        )
    except ChaosError as exc:
        raise _translate_error(exc) from exc