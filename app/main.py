import json
import logging
import os
import time
from contextlib import asynccontextmanager

from app.remediation.router import (
    remediation_action_router,
    router as remediation_router,
)
from datetime import datetime
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from app.api.rca_router import router as rca_router
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.auth.router import router as auth_router
from app.control_plane.routes import router as control_plane_router
from app.chaos.config import ChaosSettings
from app.chaos.reconciliation import reconcile_startup_runs_once
from app.chaos.router import experiments_router, router as chaos_router
from app.database import get_db
from app.deployments.router import router as deployments_router
from app.events.constants import PIPELINE_STARTED
from app.events.router import router as events_router
from app.events.service import record_platform_event
from app.incidents.incident_router import router as incidents_router
from app.incidents.incident_router import service_runtime_router
from app.incidents.service import (
    IncidentConflictError,
    IncidentNotFoundError,
)
from app.metrics_service import calculate_metrics
from app.models import Analysis, Pipeline, PipelineLog, User
from app.observability.health_router import router as health_router
from app.observability.metrics import API_REQUEST_DURATION_SECONDS
from app.observability.metrics_router import router as metrics_router
from app.reliability.router import router as reliability_router
from app.schemas import PipelineTriggerRequest
from app.tasks import execute_pipeline_task


logger = logging.getLogger(__name__)


@asynccontextmanager
async def application_lifespan(_app: FastAPI):
    if os.getenv("TESTING") != "1" and ChaosSettings.from_env().enabled:
        reconcile_startup_runs_once()
    yield


app = FastAPI(
    title="PlatformIQ(Formerly Intelligent CI/CD Platform)",
    description=(
        "A mini DevOps control plane with pipeline tracking, logs, "
        "AI failure analysis, and quality gates."
    ),
    version="1.0.0",
    lifespan=application_lifespan,
)

app.include_router(rca_router)
app.include_router(remediation_router)
app.include_router(remediation_action_router)
app.include_router(chaos_router)
app.include_router(experiments_router)


@app.exception_handler(IncidentNotFoundError)
async def incident_not_found_exception_handler(
    request: Request,
    error: IncidentNotFoundError,
):
    """Translate incident not-found domain errors into HTTP 404."""

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(error)},
    )


@app.exception_handler(IncidentConflictError)
async def incident_conflict_exception_handler(
    request: Request,
    error: IncidentConflictError,
):
    """Translate incident business conflicts into HTTP 409."""

    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(error)},
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(
    request: Request,
    error: Exception,
):
    """Log unhandled failures without exposing internal details."""

    logger.exception(
        "Unexpected API processing failure",
        exc_info=error,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Unexpected processing failure",
        },
    )


origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    os.getenv("FRONTEND_URL", ""),
]

origins = [origin for origin in origins if origin]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(incidents_router)
app.include_router(service_runtime_router)
app.include_router(metrics_router)
app.include_router(health_router)
app.include_router(events_router)
app.include_router(auth_router)
app.include_router(control_plane_router)
app.include_router(deployments_router)
app.include_router(reliability_router)


@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    start_time = time.perf_counter()

    response = await call_next(request)

    duration = time.perf_counter() - start_time

    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)

    API_REQUEST_DURATION_SECONDS.labels(
        method=request.method,
        path=path,
        status_code=str(response.status_code),
    ).observe(duration)

    return response


def safe_json_loads(value, fallback):
    if not value:
        return fallback

    try:
        return json.loads(value)
    except Exception:
        return fallback


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "message": "CI/CD platform backend is running",
    }


@app.post("/pipeline/trigger")
def trigger_pipeline(
    request: PipelineTriggerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("admin", "developer")
    ),
):
    if os.getenv("TESTING") == "1":
        return {
            "message": "Pipeline trigger accepted in test mode",
            "repo_url": request.repo_url,
            "branch": request.branch,
            "status": "PENDING",
        }

    pipeline_id = str(uuid4())

    pipeline = Pipeline(
        id=pipeline_id,
        repo_url=str(request.repo_url),
        branch=request.branch,
        status="PENDING",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(pipeline)
    db.flush()

    record_platform_event(
        db,
        event_type=PIPELINE_STARTED,
        correlation_id=str(pipeline.id),
        service_id=None,
        environment="staging",
        payload={
            "pipeline_run_id": str(pipeline.id),
            "repo_url": pipeline.repo_url,
            "branch": pipeline.branch,
            "status": pipeline.status,
            "stage": getattr(pipeline, "stage", None),
        },
    )

    db.commit()
    db.refresh(pipeline)

    execute_pipeline_task.apply_async(
        args=[pipeline_id],
        queue="pipeline_queue",
        ignore_result=True,
    )

    return {
        "pipeline_id": pipeline_id,
        "status": "PENDING",
        "message": "Pipeline triggered successfully",
    }


@app.get("/pipeline/{pipeline_id}")
def get_pipeline(
    pipeline_id: str,
    db: Session = Depends(get_db),
):
    pipeline = (
        db.query(Pipeline)
        .filter(Pipeline.id == pipeline_id)
        .first()
    )

    if not pipeline:
        raise HTTPException(
            status_code=404,
            detail="Pipeline not found",
        )

    logs = (
        db.query(PipelineLog)
        .filter(PipelineLog.pipeline_id == pipeline_id)
        .order_by(PipelineLog.timestamp.asc())
        .all()
    )

    analysis = (
        db.query(Analysis)
        .filter(Analysis.pipeline_id == pipeline_id)
        .first()
    )

    return {
        "id": pipeline.id,
        "repo_url": pipeline.repo_url,
        "branch": pipeline.branch,

        # Pipeline lifecycle
        "status": pipeline.status,
        "stage": pipeline.stage,
        "progress": pipeline.progress,
        "error_message": pipeline.error_message,
        "failure_reason": pipeline.failure_reason,

        "created_at": pipeline.created_at,
        "updated_at": pipeline.updated_at,
        "started_at": pipeline.started_at,
        "finished_at": pipeline.finished_at,
        "duration_seconds": pipeline.duration_seconds,

        # Commit metadata
        "commit_sha": pipeline.commit_sha,
        "commit_message": pipeline.commit_message,

        # Step statuses
        "build_status": pipeline.build_status,
        "test_status": pipeline.test_status,
        "sonar_status": pipeline.sonar_status,
        "trivy_status": pipeline.trivy_status,

        # SonarQube summary fields
        "quality_score": pipeline.quality_score,
        "coverage": pipeline.coverage,
        "bugs": pipeline.bugs,
        "vulnerabilities": pipeline.vulnerabilities,
        "code_smells": pipeline.code_smells,
        "duplicated_lines_density": (
            pipeline.duplicated_lines_density
        ),
        "quality_gate": pipeline.quality_gate,
        "sonar_report_url": pipeline.sonar_report_url,
        "sonar_issues": pipeline.sonar_issues or [],

        # Trivy security fields
        "trivy_critical": pipeline.trivy_critical,
        "trivy_high": pipeline.trivy_high,
        "trivy_medium": pipeline.trivy_medium,
        "trivy_low": pipeline.trivy_low,
        "trivy_unknown": pipeline.trivy_unknown,
        "trivy_total": pipeline.trivy_total,
        "trivy_report": pipeline.trivy_report or {},

        # Release risk fields
        "risk_score": pipeline.risk_score,
        "risk_level": pipeline.risk_level,
        "risk_summary": pipeline.risk_summary,

        # AI fields
        "ai_summary": pipeline.ai_summary,
        "recommendations": pipeline.recommendations or [],

        "logs": [log.log_text for log in logs],

        "analysis": {
            "failure_reason": (
                analysis.failure_reason
                if analysis
                else None
            ),
            "confidence": (
                analysis.confidence
                if analysis
                else None
            ),
            "suggestion": (
                analysis.suggestion
                if analysis
                else None
            ),
            "final_status": (
                analysis.final_status
                if analysis
                else None
            ),
            "report_json": (
                json.loads(analysis.report_json)
                if analysis and analysis.report_json
                else None
            ),
        },
    }


@app.get("/pipelines")
def list_pipelines(
    status: str | None = None,
    risk_level: str | None = None,
    branch: str | None = None,
    repo_url: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Pipeline)

    if status and status.upper() != "ALL":
        query = query.filter(
            Pipeline.status == status.upper()
        )

    if risk_level and risk_level.upper() != "ALL":
        query = query.filter(
            Pipeline.risk_level == risk_level.upper()
        )

    if branch:
        query = query.filter(
            Pipeline.branch.ilike(f"%{branch}%")
        )

    if repo_url:
        query = query.filter(
            Pipeline.repo_url.ilike(f"%{repo_url}%")
        )

    pipelines = query.order_by(
        Pipeline.created_at.desc()
    ).all()

    return [
        {
            "id": pipeline.id,
            "repo_url": pipeline.repo_url,
            "branch": pipeline.branch,

            # Pipeline lifecycle
            "status": pipeline.status,
            "stage": pipeline.stage,
            "progress": pipeline.progress,
            "created_at": pipeline.created_at,
            "updated_at": pipeline.updated_at,
            "started_at": pipeline.started_at,
            "finished_at": pipeline.finished_at,
            "duration_seconds": pipeline.duration_seconds,

            # Step statuses
            "build_status": pipeline.build_status,
            "test_status": pipeline.test_status,
            "sonar_status": pipeline.sonar_status,
            "trivy_status": pipeline.trivy_status,

            # SonarQube fields
            "coverage": pipeline.coverage,
            "bugs": pipeline.bugs,
            "vulnerabilities": pipeline.vulnerabilities,
            "code_smells": pipeline.code_smells,
            "duplicated_lines_density": (
                pipeline.duplicated_lines_density
            ),
            "quality_gate": pipeline.quality_gate,
            "sonar_report_url": pipeline.sonar_report_url,

            # Trivy summary fields
            "trivy_critical": pipeline.trivy_critical,
            "trivy_high": pipeline.trivy_high,
            "trivy_medium": pipeline.trivy_medium,
            "trivy_low": pipeline.trivy_low,
            "trivy_unknown": pipeline.trivy_unknown,
            "trivy_total": pipeline.trivy_total,

            # Release risk fields
            "risk_score": pipeline.risk_score,
            "risk_level": pipeline.risk_level,
            "risk_summary": pipeline.risk_summary,
        }
        for pipeline in pipelines
    ]


@app.get("/platform/metrics")
def get_metrics(db: Session = Depends(get_db)):
    return calculate_metrics(db)