"""HTTP routes for Sprint 7 incident operations.

The router handles authentication, authorization, HTTP error mapping, and
request/response translation. Incident business logic remains in
app.incidents.service.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.database import get_db
from app.incidents import service as incident_service
from app.incidents.enums import (
    IncidentSeverity,
    IncidentStatus,
)
from app.incidents.schemas import (
    IncidentAcknowledgeRequest,
    IncidentAssignRequest,
    IncidentCommentCreateRequest,
    IncidentCommentResponse,
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentMetricsResponse,
    IncidentMetricsSummaryResponse,
    IncidentStatusUpdateRequest,
    IncidentTimelineResponse,
)
from app.incidents.transitions import (
    InvalidIncidentTransitionError,
)
from app.models import User


INCIDENT_READ_ROLES = (
    "admin",
    "developer",
    "operator",
    "viewer",
)

INCIDENT_MANAGE_ROLES = (
    "admin",
    "developer",
    "operator",
)


def _raise_incident_error(
    error: Exception,
) -> None:
    """Translate incident domain exceptions into HTTP errors.

    This helper is retained for compatibility with existing lifecycle tests
    and any router code that needs explicit incident error translation.
    Unknown exceptions are re-raised unchanged.
    """

    if isinstance(
        error,
        incident_service.IncidentNotFoundError,
    ):
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    if isinstance(
        error,
        (
            incident_service.IncidentConflictError,
            InvalidIncidentTransitionError,
        ),
    ):
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    if isinstance(error, ValueError):
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    raise error


router = APIRouter(
    prefix="/api/incidents",
    tags=["Incidents"],
)

# Retained because main.py imports this router for service-level incident and
# runtime-timeline endpoints.
service_runtime_router = APIRouter(
    prefix="/api/services",
    tags=["runtime-timeline"],
)


@router.get(
    "",
    response_model=IncidentListResponse,
)
def list_incidents_endpoint(
    status: IncidentStatus | None = Query(
        default=None,
    ),
    severity: IncidentSeverity | None = Query(
        default=None,
    ),
    service_id: str | None = Query(
        default=None,
    ),
    environment: str | None = Query(
        default=None,
    ),
    assignee_id: str | None = Query(
        default=None,
    ),
    from_date: datetime | None = Query(
        default=None,
    ),
    to_date: datetime | None = Query(
        default=None,
    ),
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=25,
        ge=1,
        le=100,
    ),
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        require_roles(*INCIDENT_READ_ROLES)
    ),
):
    """Return a filtered and paginated incident list."""

    if (
        from_date is not None
        and to_date is not None
        and from_date > to_date
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "from_date cannot be later than "
                "to_date"
            ),
        )

    return incident_service.list_incidents(
        db,
        status=status,
        severity=severity,
        service_id=service_id,
        environment=environment,
        assignee_id=assignee_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )


# This static route must remain before /{incident_id}; otherwise FastAPI may
# attempt to interpret "metrics" as an incident UUID.
@router.get(
    "/metrics/summary",
    response_model=IncidentMetricsSummaryResponse,
)
def get_incident_metrics_summary_endpoint(
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        require_roles(*INCIDENT_READ_ROLES)
    ),
):
    """Return aggregate metrics across incidents."""

    return incident_service.get_incident_metrics_summary(
        db,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentDetailResponse,
)
def get_incident_detail_endpoint(
    incident_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        require_roles(*INCIDENT_READ_ROLES)
    ),
):
    """Return the complete details for one incident."""

    return incident_service.get_incident_detail(
        db,
        incident_id=incident_id,
    )


@router.post(
    "/{incident_id}/acknowledge",
    response_model=IncidentDetailResponse,
)
def acknowledge_incident_endpoint(
    incident_id: UUID,
    request: IncidentAcknowledgeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(*INCIDENT_MANAGE_ROLES)
    ),
):
    """Acknowledge an incident."""

    return incident_service.acknowledge_incident(
        db,
        incident_id=incident_id,
        request=request,
        actor_user_id=str(current_user.id),
    )


@router.post(
    "/{incident_id}/assign",
    response_model=IncidentDetailResponse,
)
def assign_incident_endpoint(
    incident_id: UUID,
    request: IncidentAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(*INCIDENT_MANAGE_ROLES)
    ),
):
    """Create or replace the current incident assignment."""

    return incident_service.assign_incident(
        db,
        incident_id=incident_id,
        request=request,
        assigned_by_user_id=str(current_user.id),
    )


@router.post(
    "/{incident_id}/status",
    response_model=IncidentDetailResponse,
)
def update_incident_status_endpoint(
    incident_id: UUID,
    request: IncidentStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(*INCIDENT_MANAGE_ROLES)
    ),
):
    """Apply a validated status transition to an incident."""

    return incident_service.update_incident_status(
        db,
        incident_id=incident_id,
        request=request,
        actor_user_id=str(current_user.id),
    )


@router.post(
    "/{incident_id}/comments",
    response_model=IncidentCommentResponse,
    status_code=201,
)
def add_incident_comment_endpoint(
    incident_id: UUID,
    request: IncidentCommentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(*INCIDENT_MANAGE_ROLES)
    ),
):
    """Add a comment to an incident."""

    return incident_service.add_incident_comment(
        db,
        incident_id=incident_id,
        request=request,
        actor=current_user,
    )


@router.get(
    "/{incident_id}/timeline",
    response_model=IncidentTimelineResponse,
)
def get_incident_timeline_endpoint(
    incident_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        require_roles(*INCIDENT_READ_ROLES)
    ),
):
    """Return the chronological timeline for an incident."""

    return incident_service.get_incident_timeline(
        db,
        incident_id=incident_id,
    )


@router.get(
    "/{incident_id}/metrics",
    response_model=IncidentMetricsResponse,
)
def get_incident_metrics_endpoint(
    incident_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        require_roles(*INCIDENT_READ_ROLES)
    ),
):
    """Return MTTD, MTTA, MTTR, and metric snapshots for an incident."""

    return incident_service.get_incident_metrics(
        db,
        incident_id=incident_id,
    )


@service_runtime_router.get(
    "/{service_id}/incidents",
    response_model=IncidentListResponse,
)
def get_service_incidents_endpoint(
    service_id: str,
    status: IncidentStatus | None = Query(
        default=None,
    ),
    severity: IncidentSeverity | None = Query(
        default=None,
    ),
    environment: str | None = Query(
        default=None,
    ),
    assignee_id: str | None = Query(
        default=None,
    ),
    from_date: datetime | None = Query(
        default=None,
    ),
    to_date: datetime | None = Query(
        default=None,
    ),
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=25,
        ge=1,
        le=100,
    ),
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        require_roles(*INCIDENT_READ_ROLES)
    ),
):
    """Return incidents associated with a particular service."""

    if (
        from_date is not None
        and to_date is not None
        and from_date > to_date
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "from_date cannot be later than "
                "to_date"
            ),
        )

    return incident_service.list_incidents(
        db,
        status=status,
        severity=severity,
        service_id=service_id,
        environment=environment,
        assignee_id=assignee_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )


@service_runtime_router.get(
    "/{service_id}/runtime-timeline",
    response_model=dict[str, Any],
)
def get_service_runtime_timeline_endpoint(
    service_id: str,
    environment: str | None = Query(
        default=None,
    ),
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        require_roles(*INCIDENT_READ_ROLES)
    ),
):
    """Return the combined runtime timeline for a service."""

    return incident_service.get_service_runtime_timeline(
        db,
        service_id=service_id,
        environment=environment,
    )