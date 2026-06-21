from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
    service_id: UUID
    pipeline_run_id: Optional[UUID] = None
    environment_id: Optional[UUID] = None

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

    service_id: UUID
    pipeline_run_id: Optional[UUID]
    environment_id: Optional[UUID]

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