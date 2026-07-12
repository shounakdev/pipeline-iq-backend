from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from app.reliability.query_service import (
    get_reliability_alert,
    get_service_error_budget,
    get_service_reliability,
    list_reliability_alerts,
)
from app.reliability.schemas import (
    ReliabilityAlertDetailResponse,
    ReliabilityAlertResponse,
    ServiceErrorBudgetResponse,
    ServiceReliabilityResponse,
)

from app.database import get_db
from app.reliability import slo_service
from app.reliability.prometheus_client import (
    PrometheusClientError,
    PrometheusNoDataError,
)
from app.reliability.schemas import (
    SLOCreate,
    SLOEvaluationResponse,
    SLOResponse,
)
from app.reliability.slo_engine import evaluate_slo


router = APIRouter(
    prefix="/api",
    tags=["Reliability"],
)


@router.post(
    "/services/{service_id}/slos",
    response_model=SLOResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_service_slo(
    service_id: str,
    payload: SLOCreate,
    db: Session = Depends(get_db),
):
    service = slo_service.get_service(
        db=db,
        service_id=service_id,
    )

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service not found",
        )

    return slo_service.create_slo(
        db=db,
        service_id=service_id,
        payload=payload,
    )


@router.get(
    "/services/{service_id}/slos",
    response_model=list[SLOResponse],
)
def get_service_slos(
    service_id: str,
    db: Session = Depends(get_db),
):
    service = slo_service.get_service(
        db=db,
        service_id=service_id,
    )

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service not found",
        )

    return slo_service.list_slos(
        db=db,
        service_id=service_id,
    )
    
    
@router.get(
    "/services/{service_id}/reliability",
    response_model=ServiceReliabilityResponse,
)
def read_service_reliability(
    service_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_service_reliability(
            db=db,
            service_id=service_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/services/{service_id}/error-budget",
    response_model=ServiceErrorBudgetResponse,
)
def read_service_error_budget(
    service_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_service_error_budget(
            db=db,
            service_id=service_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/alerts",
    response_model=list[ReliabilityAlertResponse],
)
def read_reliability_alerts(
    db: Session = Depends(get_db),
):
    return list_reliability_alerts(db=db)


@router.get(
    "/alerts/{alert_id}",
    response_model=ReliabilityAlertDetailResponse,
)
def read_reliability_alert(
    alert_id: str,
    db: Session = Depends(get_db),
):
    alert = get_reliability_alert(
        db=db,
        alert_id=alert_id,
    )

    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reliability alert was not found.",
        )

    return alert


@router.post(
    "/slos/{slo_definition_id}/evaluate",
    response_model=SLOEvaluationResponse,
)
def evaluate_slo_definition(
    slo_definition_id: str,
    db: Session = Depends(get_db),
):
    slo_definition = (
        slo_service.get_slo_definition(
            db=db,
            slo_definition_id=slo_definition_id,
        )
    )

    if slo_definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLO definition not found",
        )

    if not slo_definition.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SLO definition is disabled",
        )

    try:
        return evaluate_slo(
            db=db,
            slo_definition=slo_definition,
        )

    except PrometheusNoDataError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "message": (
                    "Prometheus returned no usable "
                    "metric data"
                ),
                "reason": str(exc),
            },
        ) from exc

    except PrometheusClientError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "message": "Prometheus query failed",
                "reason": str(exc),
            },
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc