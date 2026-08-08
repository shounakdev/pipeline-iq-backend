from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models import ChaosRunStatus


class ChaosRunCreateRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    environment: str = Field(min_length=1, max_length=100)
    namespace: str = Field(min_length=1, max_length=255)
    service: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    duration_seconds: int = Field(
        alias="durationSeconds",
        gt=0,
    )
    cleanup_behavior: Literal["delete"] = Field(
        alias="cleanupBehavior",
    )


class ChaosRunResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )

    id: UUID
    experiment_id: UUID
    status: ChaosRunStatus
    target_environment: str
    target_service_id: str
    target_namespace: str
    duration_seconds: int
    cleanup_behavior: str
    deadline_at: datetime
    kubernetes_resource_kind: str | None
    kubernetes_resource_name: str | None
    cleanup_succeeded: bool | None
    failure_message: str | None


class ChaosCleanupResponse(BaseModel):
    run_id: UUID
    status: ChaosRunStatus
    cleanup_succeeded: bool
