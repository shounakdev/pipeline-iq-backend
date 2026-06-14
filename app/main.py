import json
import os
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from app.auth.router import router as auth_router

from app.auth.dependencies import require_roles
from app.models import User

from app.database import Base, engine, get_db
from app.models import Pipeline, PipelineLog, Analysis
from app.schemas import PipelineTriggerRequest, PipelineResponse
from app.tasks import execute_pipeline_task
from app.metrics_service import calculate_metrics
from app.control_plane.routes import router as control_plane_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PlatformIQ(Formerly Intelligent CI/CD Platform)",
    description="A mini DevOps control plane with pipeline tracking, logs, AI failure analysis, and quality gates.",
    version="1.0.0"
)

app.include_router(auth_router)

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
app.include_router(control_plane_router)


def safe_json_loads(value, fallback):
    if not value:
        return fallback

    try:
        return json.loads(value)
    except Exception:
        return fallback


@app.get("/health")
def health_check():
    return {"status": "ok", "message": "CI/CD platform backend is running"}


@app.post("/pipeline/trigger")
def trigger_pipeline(
    request: PipelineTriggerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "developer")),
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
        updated_at=datetime.utcnow()
    )

    db.add(pipeline)
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
        "message": "Pipeline triggered successfully"
    }


@app.get("/pipeline/{pipeline_id}")
def get_pipeline(pipeline_id: str, db: Session = Depends(get_db)):
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()

    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

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
        "duplicated_lines_density": pipeline.duplicated_lines_density,
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
            "failure_reason": analysis.failure_reason if analysis else None,
            "confidence": analysis.confidence if analysis else None,
            "suggestion": analysis.suggestion if analysis else None,
            "final_status": analysis.final_status if analysis else None,
            "report_json": json.loads(analysis.report_json) if analysis and analysis.report_json else None,
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
        query = query.filter(Pipeline.status == status.upper())

    if risk_level and risk_level.upper() != "ALL":
        query = query.filter(Pipeline.risk_level == risk_level.upper())

    if branch:
        query = query.filter(Pipeline.branch.ilike(f"%{branch}%"))

    if repo_url:
        query = query.filter(Pipeline.repo_url.ilike(f"%{repo_url}%"))

    pipelines = query.order_by(Pipeline.created_at.desc()).all()

    return [
        {
            "id": p.id,
            "repo_url": p.repo_url,
            "branch": p.branch,

            # Pipeline lifecycle
            "status": p.status,
            "stage": p.stage,
            "progress": p.progress,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "started_at": p.started_at,
            "finished_at": p.finished_at,
            "duration_seconds": p.duration_seconds,

            # Step statuses
            "build_status": p.build_status,
            "test_status": p.test_status,
            "sonar_status": p.sonar_status,
            "trivy_status": p.trivy_status,

            # SonarQube fields
            "coverage": p.coverage,
            "bugs": p.bugs,
            "vulnerabilities": p.vulnerabilities,
            "code_smells": p.code_smells,
            "duplicated_lines_density": p.duplicated_lines_density,
            "quality_gate": p.quality_gate,
            "sonar_report_url": p.sonar_report_url,

            # Trivy summary fields
            "trivy_critical": p.trivy_critical,
            "trivy_high": p.trivy_high,
            "trivy_medium": p.trivy_medium,
            "trivy_low": p.trivy_low,
            "trivy_unknown": p.trivy_unknown,
            "trivy_total": p.trivy_total,

            # Release risk fields
            "risk_score": p.risk_score,
            "risk_level": p.risk_level,
            "risk_summary": p.risk_summary,
        }
        for p in pipelines
    ]

@app.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    return calculate_metrics(db)
