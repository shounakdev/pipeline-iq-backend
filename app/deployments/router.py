from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Deployment, KubernetesWorkload, DeploymentRevision

from app.events.constants import (
    DEPLOYMENT_STARTED,
    DEPLOYMENT_COMPLETED,
    DEPLOYMENT_FAILED,
)
from app.events.service import record_platform_event


router = APIRouter(prefix="/api", tags=["deployments"])


class KubernetesWorkloadCreate(BaseModel):
    workload_name: str
    namespace: str
    kind: str
    desired_replicas: int = 0
    available_replicas: int = 0
    pod_count: int = 0
    restart_count: int = 0
    status: str = "UNKNOWN"
    failure_reason: Optional[str] = None


class KubernetesWorkloadOut(KubernetesWorkloadCreate):
    id: UUID
    deployment_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeploymentCreate(BaseModel):
    service_id: str
    pipeline_run_id: Optional[str] = None
    environment_id: Optional[str] = None

    commit_sha: Optional[str] = None
    image_tag: str
    deployment_version: Optional[str] = None

    argo_sync_status: Optional[str] = "UNKNOWN"
    kubernetes_rollout_status: Optional[str] = "UNKNOWN"
    previous_revision: Optional[str] = None

    namespace: Optional[str] = None
    cluster_name: Optional[str] = "kind-platformiq"
    service_name: Optional[str] = None
    argo_application_name: Optional[str] = None

    pod_count: Optional[int] = 0
    restart_count: Optional[int] = 0
    failure_reason: Optional[str] = None

    deployed_at: Optional[datetime] = None

    workloads: Optional[List[KubernetesWorkloadCreate]] = None


class DeploymentOut(BaseModel):
    id: UUID

    service_id: str
    pipeline_run_id: Optional[str]
    environment_id: Optional[str]

    commit_sha: Optional[str]
    image_tag: str
    deployment_version: Optional[str]

    argo_sync_status: Optional[str]
    kubernetes_rollout_status: Optional[str]
    previous_revision: Optional[str]

    namespace: Optional[str]
    cluster_name: Optional[str]
    service_name: Optional[str]
    argo_application_name: Optional[str]

    pod_count: Optional[int]
    restart_count: Optional[int]
    failure_reason: Optional[str]

    created_at: datetime
    deployed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


@router.post("/deployments", response_model=DeploymentOut)
def create_deployment(
    request: DeploymentCreate,
    db: Session = Depends(get_db),
):
    deployment_data = request.model_dump(exclude={"workloads"})

    if deployment_data.get("deployed_at") is None:
        deployment_data["deployed_at"] = datetime.now(timezone.utc)

    deployment = Deployment(**deployment_data)

    db.add(deployment)
    db.flush()

    if request.workloads:
        for workload_request in request.workloads:
            workload = KubernetesWorkload(
                deployment_id=deployment.id,
                **workload_request.model_dump(),
            )
            db.add(workload)

    revision = DeploymentRevision(
        deployment_id=deployment.id,
        revision=request.deployment_version,
        image_tag=request.image_tag,
        commit_sha=request.commit_sha,
        status=request.kubernetes_rollout_status,
        deployed_at=deployment.deployed_at,
    )

    db.add(revision)

    record_platform_event(
        db,
        event_type=DEPLOYMENT_STARTED,
        correlation_id=str(deployment.pipeline_run_id or deployment.id),
        service_id=str(deployment.service_id),
        environment=getattr(deployment, "environment", None) or "staging",
        payload={
            "deployment_id": str(deployment.id),
            "pipeline_run_id": str(deployment.pipeline_run_id)
            if deployment.pipeline_run_id
            else None,
            "image_tag": deployment.image_tag,
            "deployment_version": deployment.deployment_version,
            "namespace": deployment.namespace,
            "cluster_name": deployment.cluster_name,
            "argo_application_name": deployment.argo_application_name,
        },
    )

    db.commit()
    db.refresh(deployment)

    return deployment


@router.get("/deployments", response_model=list[DeploymentOut])
def list_deployments(
    service_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Deployment)

    if service_id:
        query = query.filter(Deployment.service_id == service_id)

    return query.order_by(Deployment.created_at.desc()).all()


@router.get("/services/{service_id}/deployments", response_model=list[DeploymentOut])
def list_service_deployments(
    service_id: str,
    db: Session = Depends(get_db),
):
    deployments = (
        db.query(Deployment)
        .filter(Deployment.service_id == service_id)
        .order_by(Deployment.created_at.desc())
        .all()
    )

    return deployments


@router.get("/deployments/{deployment_id}", response_model=DeploymentOut)
def get_deployment(
    deployment_id: UUID,
    db: Session = Depends(get_db),
):
    deployment = (
        db.query(Deployment)
        .filter(Deployment.id == deployment_id)
        .first()
    )

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    return deployment


@router.get(
    "/deployments/{deployment_id}/workloads",
    response_model=list[KubernetesWorkloadOut],
)
def get_deployment_workloads(
    deployment_id: UUID,
    db: Session = Depends(get_db),
):
    deployment = (
        db.query(Deployment)
        .filter(Deployment.id == deployment_id)
        .first()
    )

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    workloads = (
        db.query(KubernetesWorkload)
        .filter(KubernetesWorkload.deployment_id == deployment_id)
        .order_by(KubernetesWorkload.created_at.desc())
        .all()
    )

    return workloads


@router.post(
    "/deployments/{deployment_id}/workloads",
    response_model=KubernetesWorkloadOut,
)
def create_deployment_workload(
    deployment_id: UUID,
    request: KubernetesWorkloadCreate,
    db: Session = Depends(get_db),
):
    deployment = (
        db.query(Deployment)
        .filter(Deployment.id == deployment_id)
        .first()
    )

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    workload = KubernetesWorkload(
        deployment_id=deployment_id,
        **request.model_dump(),
    )

    previous_rollout_status = (
        deployment.kubernetes_rollout_status or "UNKNOWN"
    ).upper()

    requested_status = (request.status or "UNKNOWN").upper()

    deployment.pod_count = request.pod_count
    deployment.restart_count = request.restart_count

    failed_statuses = {
        "FAILED",
        "FAILURE",
        "ERROR",
        "UNHEALTHY",
        "DEGRADED",
        "CRASHLOOPBACKOFF",
        "IMAGEPULLBACKOFF",
    }

    completed_statuses = {
        "HEALTHY",
        "SUCCESS",
        "SUCCEEDED",
        "READY",
        "AVAILABLE",
        "SYNCED",
    }

    if request.failure_reason or requested_status in failed_statuses:
        deployment.kubernetes_rollout_status = "FAILED"
        deployment.failure_reason = (
            request.failure_reason
            or f"Workload {request.workload_name} reported status {request.status}"
        )

        if previous_rollout_status != "FAILED":
            record_platform_event(
                db,
                event_type=DEPLOYMENT_FAILED,
                correlation_id=str(deployment.pipeline_run_id or deployment.id),
                service_id=str(deployment.service_id),
                environment=getattr(deployment, "environment", None) or "staging",
                payload={
                    "deployment_id": str(deployment.id),
                    "pipeline_run_id": str(deployment.pipeline_run_id)
                    if deployment.pipeline_run_id
                    else None,
                    "image_tag": deployment.image_tag,
                    "argo_sync_status": deployment.argo_sync_status,
                    "kubernetes_rollout_status": deployment.kubernetes_rollout_status,
                    "failure_reason": deployment.failure_reason,
                },
            )

    elif requested_status in completed_statuses:
        deployment.argo_sync_status = "SYNCED"
        deployment.kubernetes_rollout_status = "HEALTHY"

        if previous_rollout_status != "HEALTHY":
            record_platform_event(
                db,
                event_type=DEPLOYMENT_COMPLETED,
                correlation_id=str(deployment.pipeline_run_id or deployment.id),
                service_id=str(deployment.service_id),
                environment=getattr(deployment, "environment", None) or "staging",
                payload={
                    "deployment_id": str(deployment.id),
                    "pipeline_run_id": str(deployment.pipeline_run_id)
                    if deployment.pipeline_run_id
                    else None,
                    "image_tag": deployment.image_tag,
                    "argo_sync_status": deployment.argo_sync_status,
                    "kubernetes_rollout_status": deployment.kubernetes_rollout_status,
                    "pod_count": deployment.pod_count,
                    "restart_count": deployment.restart_count,
                },
            )

    else:
        deployment.kubernetes_rollout_status = request.status

    db.add(workload)
    db.commit()
    db.refresh(workload)

    return workload