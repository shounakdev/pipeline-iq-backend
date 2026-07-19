"""Shared request and response schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class RequestSchema(BaseModel):
    """Base class for API request schemas."""

    model_config = ConfigDict(
        extra="forbid",
    )


class ResponseSchema(BaseModel):
    """Base class for API response schemas."""

    model_config = ConfigDict(
        from_attributes=True,
    )


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


class ProjectResponse(ResponseSchema):
    id: str
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime


class ServiceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    service_type: str = "web"
    owner: Optional[str] = None


class ServiceResponse(ResponseSchema):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    service_type: str | None = None
    owner: Optional[str] = None
    created_at: datetime


class RepositoryCreate(BaseModel):
    provider: str = "github"
    repo_url: HttpUrl
    default_branch: str = "main"


class RepositoryResponse(ResponseSchema):
    id: str
    service_id: str
    provider: str
    repo_url: str
    default_branch: str
    created_at: datetime


class EnvironmentCreate(BaseModel):
    name: str = "development"
    is_active: bool = True


class EnvironmentResponse(ResponseSchema):
    id: str
    service_id: str
    name: str
    is_active: bool
    created_at: datetime


class AuditEventResponse(ResponseSchema):
    id: str
    actor_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    details_json: Optional[str] = None
    created_at: datetime


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
    services: list[ServiceResponse] = Field(
        default_factory=list,
    )


class ServiceDetailResponse(ServiceResponse):
    repositories: list[RepositoryResponse] = Field(
        default_factory=list,
    )
    environments: list[EnvironmentResponse] = Field(
        default_factory=list,
    )