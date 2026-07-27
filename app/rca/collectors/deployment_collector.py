from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Deployment


DEFAULT_DEPLOYMENT_CORRELATION_WINDOW_MINUTES = 60


def collect_deployment_evidence(
    db: Session,
    incident: dict,
    correlation_window_minutes: int = DEFAULT_DEPLOYMENT_CORRELATION_WINDOW_MINUTES,
) -> dict:
    suspected_deployment_id = incident.get("suspected_deployment_id")

    if suspected_deployment_id:
        deployment = db.query(Deployment).filter(Deployment.id == suspected_deployment_id).first()

        if deployment:
            return _serialize_deployment(
                deployment=deployment,
                incident=incident,
                correlation_method="SUSPECTED_DEPLOYMENT_ID",
            )

    failure_started_at = incident.get("failure_started_at")
    service_id = incident.get("primary_service_id")

    if not failure_started_at or not service_id:
        return {
            "status": "NO_DATA",
            "reason": "Missing incident failure time or service for deployment correlation",
            "correlation_method": "NO_DATA",
        }

    window_start = failure_started_at - timedelta(minutes=correlation_window_minutes)

    deployment = (
        db.query(Deployment)
        .filter(Deployment.service_id == service_id)
        .filter(Deployment.deployed_at <= failure_started_at)
        .filter(Deployment.deployed_at >= window_start)
        .order_by(Deployment.deployed_at.desc())
        .first()
    )

    if not deployment:
        return {
            "status": "NO_DATA",
            "reason": "No deployment found within correlation window",
            "correlation_method": "NO_DATA",
        }

    return _serialize_deployment(
        deployment=deployment,
        incident=incident,
        correlation_method="LATEST_DEPLOYMENT_BEFORE_FAILURE",
    )


def _serialize_deployment(
    deployment: Deployment,
    incident: dict,
    correlation_method: str,
) -> dict:
    deployed_at = deployment.deployed_at
    failure_started_at = incident.get("failure_started_at")

    minutes_before_failure = None
    if deployed_at and failure_started_at:
        minutes_before_failure = int(
            (failure_started_at - deployed_at).total_seconds() // 60
        )

    return {
        "status": "COLLECTED",
        "deployment_id": str(deployment.id),
        "version": deployment.deployment_version or deployment.image_tag,
        "commit_sha": deployment.commit_sha,
        "deployment_status": deployment.kubernetes_rollout_status
        or deployment.argo_sync_status,
        "deployed_at": deployed_at,
        "minutes_before_failure": minutes_before_failure,
        "service_id": str(deployment.service_id),
        "environment": (
            str(deployment.environment_id)
            if deployment.environment_id
            else None
        ),
        "pipeline_run_id": (
            str(deployment.pipeline_run_id)
            if deployment.pipeline_run_id
            else None
        ),
        "correlation_method": correlation_method,
    }