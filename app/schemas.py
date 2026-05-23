from pydantic import BaseModel, HttpUrl


class PipelineTriggerRequest(BaseModel):
    repo_url: HttpUrl
    branch: str = "main"


class PipelineResponse(BaseModel):
    pipeline_id: str
    status: str