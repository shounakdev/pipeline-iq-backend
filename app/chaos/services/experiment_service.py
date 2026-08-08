"""Experiment validation and durable PENDING run creation."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.chaos import repository
from app.chaos.config import ChaosSettings
from app.chaos.exceptions import (
    ChaosConflictError,
    ChaosExperimentNotFoundError,
)
from app.chaos.schemas import ChaosRunCreateRequest
from app.chaos.services.safety_service import validate_run_request
from app.models import (
    ChaosExperiment,
    ChaosRun,
    ChaosRunStatus,
    ChaosScenarioType,
    Service,
)


def resolve_experiment(
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


def create_pending_run(
    *,
    db: Session,
    request: ChaosRunCreateRequest,
    operator_id: str,
    settings: ChaosSettings,
) -> ChaosRun:
    """Validate and persist a run without performing any slow I/O."""
    validate_run_request(request, settings)
    experiment = resolve_experiment(db, request)
    started_at = datetime.now(timezone.utc)

    try:
        run = repository.create_run(
            db,
            experiment_id=experiment.id,
            triggered_by=operator_id,
            status=ChaosRunStatus.PENDING,
            started_at=started_at,
            duration_seconds=request.duration_seconds,
            cleanup_behavior=request.cleanup_behavior,
            deadline_at=started_at
            + timedelta(seconds=request.duration_seconds),
        )
        db.commit()
        db.refresh(run)
        return run
    except IntegrityError as exc:
        db.rollback()
        raise ChaosConflictError(
            "Another chaos experiment is already active"
        ) from exc