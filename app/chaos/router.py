from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
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
)
from app.chaos.service import cleanup_chaos_run, get_run_or_raise
from app.chaos.services.experiment_service import create_pending_run
from app.chaos.tasks import execute_chaos_run
from app.database import get_db
from app.models import User


router = APIRouter(prefix="/api/chaos", tags=["Chaos Engineering"])
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