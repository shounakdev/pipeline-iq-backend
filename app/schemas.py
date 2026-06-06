from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, HttpUrl


class PipelineTriggerRequest(BaseModel):
    repo_url: HttpUrl
    branch: str = "main"


class PipelineResponse(BaseModel):
    pipeline_id: str
    status: str


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ServiceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    service_type: str = "web"
    owner: Optional[str] = None


class ServiceResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    service_type: str
    owner: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RepositoryCreate(BaseModel):
    provider: str = "github"
    repo_url: HttpUrl
    default_branch: str = "main"


class RepositoryResponse(BaseModel):
    id: str
    service_id: str
    provider: str
    repo_url: str
    default_branch: str
    created_at: datetime

    class Config:
        from_attributes = True


class EnvironmentCreate(BaseModel):
    name: str = "development"
    is_active: bool = True


class EnvironmentResponse(BaseModel):
    id: str
    service_id: str
    name: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AuditEventResponse(BaseModel):
    id: str
    actor_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    details_json: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ServicePipelineTriggerRequest(BaseModel):
    branch: Optional[str] = None


class ServicePipelineTriggerResponse(BaseModel):
    pipeline_id: str
    service_id: str
    repository_id: str
    repo_url: str
    branch: str
    status: str
    message: str


class ProjectDetailResponse(ProjectResponse):
    services: list[ServiceResponse] = []


class ServiceDetailResponse(ServiceResponse):
    repositories: list[RepositoryResponse] = []
    environments: list[EnvironmentResponse] = []