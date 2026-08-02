import json
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.database import get_db
from app.models import (
    RemediationRecommendation,
    User,
)
from app.remediation import repository
from app.remediation.approval_service import (
    RejectionReasonRequiredError,
    RemediationAlreadyDecidedError,
    RemediationNotFoundError,
    approve_remediation,
    reject_remediation,
)
from app.remediation.recommendation_service import (
    IncidentEvidenceMissingError,
    IncidentNotFoundError,
    NoSafeRemediationError,
    RCAReportMissingError,
    RecommendationInputsNotChangedError,
    recommend_remediation,
)
from app.remediation.schemas import (
    RecoveryVerificationRecordResponse,
    RecoveryVerificationResponse,
    RemediationAuditEventResponse,
    RemediationDetailResponse,
    RemediationExecutionRecordResponse,
    RemediationExecutionResponse,
    RemediationRecommendationResponse,
    RemediationRejectionRequest,
    RemediationStatusResponse,
)
from app.remediation.services.execution_service import (
    RemediationExecutionError,
    execute_remediation,
)
from app.remediation.services import safety_service
from app.remediation.services.verification_service import (
    RecoveryHealthSnapshotMissingError,
    RemediationExecutionIncompleteError,
    RemediationExecutionNotFoundError,
    RemediationNotFoundError as VerificationRemediationNotFoundError,
    verify_remediation_recovery,
)


router = APIRouter(
    prefix="/api/incidents",
    tags=["Incident Remediation"],
)

remediation_action_router = APIRouter(
    prefix="/api/remediations",
    tags=["Remediation Approval"],
)


recommendation_roles = require_roles(
    "admin",
    "operator",
)

approval_roles = require_roles(
    "admin",
    "operator",
)

remediation_read_roles = require_roles(
    "admin",
    "operator",
    "developer",
    "viewer",
)


def _error_detail(
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
    }


def _build_status_response(
    recommendation,
    approval,
) -> RemediationStatusResponse:
    recommendation_response = (
        RemediationRecommendationResponse
        .model_validate(recommendation)
    )

    return RemediationStatusResponse(
        **recommendation_response.model_dump(),
        approval=approval,
    )


def _parse_audit_details(
    raw_details: Any,
) -> dict[str, Any]:
    if isinstance(raw_details, dict):
        return raw_details

    if not isinstance(raw_details, str):
        return {}

    cleaned_details = raw_details.strip()

    if not cleaned_details:
        return {}

    try:
        parsed_details = json.loads(cleaned_details)
    except json.JSONDecodeError:
        return {
            "raw": cleaned_details,
        }

    if isinstance(parsed_details, dict):
        return parsed_details

    return {
        "value": parsed_details,
    }


def _build_detail_response(
    db: Session,
    recommendation: RemediationRecommendation,
) -> RemediationDetailResponse:
    status_response = _build_status_response(
        recommendation,
        recommendation.approval,
    )

    execution = (
        repository.get_execution_by_remediation_id(
            db,
            recommendation.id,
        )
    )

    verification = None

    if execution is not None:
        verification = (
            repository
            .get_recovery_verification_for_execution(
                db,
                execution.id,
            )
        )

    audit_events = (
        repository.list_remediation_audit_events(
            db,
            recommendation.id,
        )
    )

    execution_response = (
        RemediationExecutionRecordResponse
        .model_validate(execution)
        if execution is not None
        else None
    )

    verification_response = (
        RecoveryVerificationRecordResponse
        .model_validate(verification)
        if verification is not None
        else None
    )

    audit_history = [
        RemediationAuditEventResponse(
            id=audit_event.id,
            actor_id=audit_event.actor_id,
            action=audit_event.action,
            entity_type=audit_event.entity_type,
            entity_id=audit_event.entity_id,
            details=_parse_audit_details(
                audit_event.details,
            ),
            created_at=audit_event.created_at,
        )
        for audit_event in audit_events
    ]

    return RemediationDetailResponse(
        **status_response.model_dump(),
        execution=execution_response,
        verification=verification_response,
        audit_history=audit_history,
    )


@router.post(
    "/{incident_id}/remediation/recommend",
    response_model=RemediationRecommendationResponse,
    status_code=status.HTTP_200_OK,
    responses={
        201: {
            "description": (
                "Recommendation created"
            ),
        },
        409: {
            "description": (
                "RCA or incident evidence is "
                "missing or unchanged"
            ),
        },
        422: {
            "description": (
                "No safe remediation rule matched"
            ),
        },
    },
)
def recommend_incident_remediation(
    incident_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        recommendation_roles,
    ),
):
    """
    Create or return an evidence-grounded remediation
    recommendation.

    This endpoint never executes a remediation action.
    """

    try:
        result = recommend_remediation(
            db=db,
            incident_id=incident_id,
            created_by=str(current_user.id),
        )
    except IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "INCIDENT_NOT_FOUND",
                str(exc),
            ),
        ) from exc
    except IncidentEvidenceMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "INCIDENT_EVIDENCE_MISSING",
                str(exc),
            ),
        ) from exc
    except RCAReportMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "RCA_REPORT_MISSING",
                str(exc),
            ),
        ) from exc
    except RecommendationInputsNotChangedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "RECOMMENDATION_INPUTS_NOT_CHANGED",
                str(exc),
            ),
        ) from exc
    except NoSafeRemediationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=_error_detail(
                "NO_SAFE_REMEDIATION",
                str(exc),
            ),
        ) from exc

    response.status_code = (
        status.HTTP_201_CREATED
        if result.created
        else status.HTTP_200_OK
    )

    return result.recommendation


@router.get(
    "/{incident_id}/remediations",
    response_model=list[
        RemediationRecommendationResponse
    ],
)
def list_remediations_for_incident(
    incident_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        remediation_read_roles,
    ),
):
    incident = repository.get_incident_by_id(
        db,
        incident_id,
    )

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "INCIDENT_NOT_FOUND",
                "Incident was not found",
            ),
        )

    return repository.list_incident_remediations(
        db,
        incident_id,
    )


@remediation_action_router.get(
    "",
    response_model=list[RemediationDetailResponse],
)
def list_all_remediation_recommendations(
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        remediation_read_roles,
    ),
):
    recommendations = (
        repository.list_all_remediations(db)
    )

    return [
        _build_detail_response(
            db,
            recommendation,
        )
        for recommendation in recommendations
    ]


@remediation_action_router.post(
    "/{remediation_id}/approve",
    response_model=RemediationStatusResponse,
)
def approve_remediation_recommendation(
    remediation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        approval_roles,
    ),
):
    try:
        result = approve_remediation(
            db=db,
            remediation_id=remediation_id,
            approved_by=str(current_user.id),
        )
    except RemediationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "REMEDIATION_NOT_FOUND",
                str(exc),
            ),
        ) from exc
    except RemediationAlreadyDecidedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "REMEDIATION_ALREADY_DECIDED",
                str(exc),
            ),
        ) from exc

    return _build_status_response(
        result.recommendation,
        result.approval,
    )


@remediation_action_router.post(
    "/{remediation_id}/reject",
    response_model=RemediationStatusResponse,
)
def reject_remediation_recommendation(
    remediation_id: UUID,
    request: RemediationRejectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        approval_roles,
    ),
):
    try:
        result = reject_remediation(
            db=db,
            remediation_id=remediation_id,
            rejected_by=str(current_user.id),
            rejection_reason=(
                request.rejection_reason
            ),
        )
    except RemediationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "REMEDIATION_NOT_FOUND",
                str(exc),
            ),
        ) from exc
    except RemediationAlreadyDecidedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "REMEDIATION_ALREADY_DECIDED",
                str(exc),
            ),
        ) from exc
    except RejectionReasonRequiredError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=_error_detail(
                "REJECTION_REASON_REQUIRED",
                str(exc),
            ),
        ) from exc

    return _build_status_response(
        result.recommendation,
        result.approval,
    )


@remediation_action_router.get(
    "/{remediation_id}/status",
    response_model=RemediationStatusResponse,
)
def get_remediation_status(
    remediation_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        remediation_read_roles,
    ),
):
    remediation = repository.get_remediation_by_id(
        db,
        remediation_id,
    )

    if remediation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "REMEDIATION_NOT_FOUND",
                "Remediation recommendation was not found",
            ),
        )

    return _build_status_response(
        remediation,
        remediation.approval,
    )


@remediation_action_router.get(
    "/{remediation_id}/detail",
    response_model=RemediationDetailResponse,
)
def get_remediation_detail(
    remediation_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        remediation_read_roles,
    ),
):
    remediation = repository.get_remediation_by_id(
        db,
        remediation_id,
    )

    if remediation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "REMEDIATION_NOT_FOUND",
                (
                    "Remediation recommendation "
                    "was not found"
                ),
            ),
        )

    return _build_detail_response(
        db,
        remediation,
    )


@remediation_action_router.post(
    "/{remediation_id}/execute",
    response_model=RemediationExecutionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "description": (
                "Remediation recommendation was not found"
            ),
        },
        409: {
            "description": (
                "Execution blocked by a remediation "
                "safety guardrail"
            ),
        },
        502: {
            "description": (
                "Remediation adapter execution failed"
            ),
        },
    },
)
def execute_remediation_recommendation(
    remediation_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        approval_roles,
    ),
):
    try:
        result = execute_remediation(
            db=db,
            remediation_id=remediation_id,
        )
    except safety_service.RemediationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "REMEDIATION_NOT_FOUND",
                str(exc),
            ),
        ) from exc
    except safety_service.RemediationSafetyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "REMEDIATION_EXECUTION_BLOCKED",
                str(exc),
            ),
        ) from exc
    except RemediationExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_error_detail(
                "REMEDIATION_EXECUTION_FAILED",
                str(exc),
            ),
        ) from exc

    output = result.output

    return RemediationExecutionResponse(
        execution_id=result.execution.id,
        remediation_id=result.recommendation.id,
        action_type=(
            result.recommendation.action_type
        ),
        command_type=output["command_type"],
        status=output["status"],
        message=output["message"],
        target_revision=output.get(
            "target_revision"
        ),
        target_pod=output.get("target_pod"),
        replica_count=output.get(
            "replica_count"
        ),
        simulated=bool(
            result.execution.command_payload.get(
                "simulated",
                False,
            )
        ),
        started_at=result.execution.started_at,
        completed_at=result.execution.completed_at,
    )


@remediation_action_router.get(
    "/{remediation_id}/verification",
    response_model=RecoveryVerificationResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "description": (
                "Remediation or execution was not found"
            ),
        },
        409: {
            "description": (
                "Execution is incomplete or post-execution "
                "health data is unavailable"
            ),
        },
    },
)
def get_remediation_verification(
    remediation_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(
        approval_roles,
    ),
):
    try:
        result = verify_remediation_recovery(
            db=db,
            remediation_id=remediation_id,
        )
    except VerificationRemediationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "REMEDIATION_NOT_FOUND",
                str(exc),
            ),
        ) from exc
    except RemediationExecutionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(
                "REMEDIATION_EXECUTION_NOT_FOUND",
                str(exc),
            ),
        ) from exc
    except RemediationExecutionIncompleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "REMEDIATION_EXECUTION_INCOMPLETE",
                str(exc),
            ),
        ) from exc
    except RecoveryHealthSnapshotMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "RECOVERY_HEALTH_SNAPSHOT_MISSING",
                str(exc),
            ),
        ) from exc

    verification = result.verification

    return RecoveryVerificationResponse(
        verification_id=verification.id,
        remediation_id=(
            verification.remediation_id
        ),
        execution_id=(
            verification.remediation_execution_id
        ),
        status=verification.verification_status,
        recovered=result.recovered,
        error_rate_recovered=(
            verification.error_rate_recovered
        ),
        latency_recovered=(
            verification.latency_recovered
        ),
        pods_healthy=verification.pods_healthy,
        restart_loop_absent=(
            verification.restart_loop_absent
        ),
        availability_restored=(
            verification.availability_restored
        ),
        metrics_snapshot=(
            verification.metrics_snapshot
        ),
        verified_at=verification.verified_at,
    )
