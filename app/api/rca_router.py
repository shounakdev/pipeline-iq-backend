from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models import RCAReportStatus
from app.rca.api_schemas import (
    RCAEvidenceResponse,
    RCAFeedbackRequest,
    RCAFeedbackResponse,
    RCAGenerateRequest,
    RCAGenerateResponse,
    RCAReportBody,
    RCAStatusResponse,
)
from app.rca.services.rca_api_service import (
    RCAAPIConflictError,
    RCAAPINotFoundError,
    create_feedback,
    get_latest_evidence,
    get_latest_report,
)
from app.rca.services.rca_generation_service import (
    RCAGenerationAlreadyActiveError,
    RCAGenerationQueueUnavailableError,
    request_rca_generation,
)


router = APIRouter(
    prefix="/api/incidents",
    tags=["Incident RCA"],
)


generate_roles = require_roles("admin", "developer", "operator")
read_roles = require_roles("admin", "developer", "operator", "viewer")
feedback_roles = require_roles("admin", "developer", "operator", "viewer")


def _status_value(value) -> str:
    return getattr(value, "value", value)


def _report_payload(report) -> dict:
    payload = getattr(report, "report_json", None)
    return payload if isinstance(payload, dict) else {}


def _evidence_payload(evidence) -> dict:
    payload = (
        getattr(evidence, "evidence_payload", None)
        or getattr(evidence, "evidence_json", None)
    )
    return payload if isinstance(payload, dict) else {}


def _source_statuses(evidence, payload: dict) -> dict:
    direct = getattr(evidence, "source_statuses", None)

    if isinstance(direct, dict):
        return direct

    payload_statuses = payload.get("source_statuses")
    if isinstance(payload_statuses, dict):
        return payload_statuses

    statuses = {}
    for source in [
        "deployment",
        "pipeline",
        "slo",
        "metrics",
        "logs",
        "traces",
        "kubernetes",
    ]:
        source_payload = payload.get(source)
        if isinstance(source_payload, dict):
            statuses[source] = source_payload.get("status", "NO_DATA")
        else:
            statuses[source] = "NO_DATA"

    return statuses


def _missing_sources(evidence, payload: dict) -> list:
    direct = getattr(evidence, "missing_sources", None)

    if isinstance(direct, list):
        return direct

    payload_missing = payload.get("missing_sources")
    if isinstance(payload_missing, list):
        return payload_missing

    return [
        source
        for source, source_status in _source_statuses(evidence, payload).items()
        if source_status in {"NO_DATA", "FAILED"}
    ]


@router.post(
    "/{incident_id}/rca/generate",
    response_model=RCAGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(generate_roles)],
)
def generate_incident_rca(
    incident_id: UUID,
    request: RCAGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        result = request_rca_generation(
            db=db,
            incident_id=incident_id,
            requested_by=getattr(current_user, "id", None),
            force_regenerate=request.force_regenerate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RCAGenerationAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RCAGenerationQueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return RCAGenerateResponse(
        incident_id=result.get("incident_id"),
        evidence_id=result.get("evidence_id"),
        rca_report_id=result.get("report_id"),
        status=_status_value(result.get("status")),
    )


@router.get(
    "/{incident_id}/evidence",
    response_model=RCAEvidenceResponse,
    dependencies=[Depends(read_roles)],
)
def get_incident_evidence(
    incident_id: UUID,
    version: int | None = Query(default=None, ge=1),
    include_collector_errors: bool = False,
    db: Session = Depends(get_db),
):
    try:
        evidence = get_latest_evidence(db, incident_id, version)
    except RCAAPINotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = _evidence_payload(evidence)

    return RCAEvidenceResponse(
        incident_id=evidence.incident_id,
        evidence_id=evidence.id,
        status=_status_value(evidence.status),
        version=evidence.version,
        source_statuses=_source_statuses(evidence, payload),
        completeness_score=getattr(evidence, "completeness_score", None),
        missing_sources=_missing_sources(evidence, payload),
        evidence=payload,
        collector_errors=(
            getattr(evidence, "collection_errors", None) or []
        )
        if include_collector_errors
        else None,
        collection_started_at=getattr(evidence, "collection_started_at", None),
        collected_at=(
            getattr(evidence, "collected_at", None)
            or getattr(evidence, "collection_completed_at", None)
        ),
        created_at=evidence.created_at,
    )


@router.get(
    "/{incident_id}/rca",
    response_model=RCAStatusResponse,
    dependencies=[Depends(read_roles)],
)
def get_incident_rca(
    incident_id: UUID,
    db: Session = Depends(get_db),
):
    try:
        report = get_latest_report(db, incident_id)
    except RCAAPINotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    report_status = _status_value(report.status)
    payload = _report_payload(report)

    if report_status in {
        RCAReportStatus.PENDING.value,
        RCAReportStatus.GENERATING.value,
    }:
        return RCAStatusResponse(status=report_status, report=None)

    failure_reason = (
        getattr(report, "failure_reason", None)
        or getattr(report, "error_message", None)
        or payload.get("failure_reason")
    )

    probable_root_cause = payload.get("probable_root_cause")
    if not probable_root_cause and failure_reason:
        probable_root_cause = (
            "RCA generation completed with low confidence because the collected "
            "evidence bundle did not match the strict RCA report schema."
        )

    confidence_explanation = payload.get("confidence_explanation")
    if not confidence_explanation and failure_reason:
        confidence_explanation = (
            "Confidence is low because evidence was collected, but strict RCA "
            "validation failed before a full report could be generated."
        )

    root_cause_category = payload.get("root_cause_category")
    if not root_cause_category and failure_reason:
        root_cause_category = "INSUFFICIENT_STRUCTURED_EVIDENCE"

    return RCAStatusResponse(
        status=report_status,
        report=RCAReportBody(
            probable_root_cause=probable_root_cause,
            root_cause_category=root_cause_category,
            confidence=(
                _status_value(report.confidence)
                if report.confidence
                else payload.get("confidence")
            ),
            confidence_explanation=confidence_explanation,
            supporting_evidence=payload.get("supporting_evidence", []),
            recommended_actions=payload.get("recommended_actions", []),
            alternative_hypotheses=payload.get("alternative_hypotheses", []),
            missing_evidence=payload.get("missing_evidence", []),
            failure_reason=failure_reason,
        ),
    )


@router.post(
    "/{incident_id}/rca/feedback",
    response_model=RCAFeedbackResponse,
    dependencies=[Depends(feedback_roles)],
)
def submit_incident_rca_feedback(
    incident_id: UUID,
    request: RCAFeedbackRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        feedback = create_feedback(
            db=db,
            incident_id=incident_id,
            report_id=request.rca_report_id,
            rating=request.rating,
            comment=request.comment,
            submitted_by=getattr(current_user, "id", None),
        )
    except RCAAPINotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RCAAPIConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RCAFeedbackResponse(
        id=feedback.id,
        incident_id=feedback.incident_id,
        rca_report_id=feedback.report_id,
        rating=_status_value(feedback.rating),
        comment=feedback.comment,
        submitted_by=feedback.reviewer_id,
        created_at=feedback.created_at,
    )