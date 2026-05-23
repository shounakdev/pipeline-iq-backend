import json
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine, get_db
from app.models import Pipeline, PipelineLog, Analysis
from app.schemas import PipelineTriggerRequest, PipelineResponse
from app.tasks import execute_pipeline_task
from app.metrics_service import calculate_metrics


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Intelligent CI/CD Platform",
    description="A mini DevOps control plane with pipeline tracking, logs, AI failure analysis, and quality gates.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
def trigger_pipeline(request: PipelineTriggerRequest, db: Session = Depends(get_db)):
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

    execute_pipeline_task.delay(pipeline_id)

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
        "status": pipeline.status,
        "created_at": pipeline.created_at,
        "updated_at": pipeline.updated_at,
        "started_at": pipeline.started_at,
        "finished_at": pipeline.finished_at,
        "duration_seconds": pipeline.duration_seconds,

        # SonarQube summary fields
        "coverage": pipeline.coverage,
        "bugs": pipeline.bugs,
        "vulnerabilities": pipeline.vulnerabilities,
        "code_smells": pipeline.code_smells,
        "duplicated_lines_density": pipeline.duplicated_lines_density,
        "quality_gate": pipeline.quality_gate,
        "sonar_report_url": pipeline.sonar_report_url,
        "sonar_issues": safe_json_loads(pipeline.sonar_issues_json, []),

        "logs": [log.log_text for log in logs],

        "analysis": {
            "failure_reason": analysis.failure_reason if analysis else None,
            "confidence": analysis.confidence if analysis else None,
            "suggestion": analysis.suggestion if analysis else None,
            "final_status": analysis.final_status if analysis else None,
            "report_json": json.loads(analysis.report_json) if analysis and analysis.report_json else None,
        }
    }


@app.get("/pipelines")
def list_pipelines(db: Session = Depends(get_db)):
    pipelines = db.query(Pipeline).order_by(Pipeline.created_at.desc()).all()

    return [
        {
            "id": p.id,
            "repo_url": p.repo_url,
            "branch": p.branch,
            "status": p.status,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "duration_seconds": p.duration_seconds,

            # SonarQube table fields
            "coverage": p.coverage,
            "bugs": p.bugs,
            "vulnerabilities": p.vulnerabilities,
            "code_smells": p.code_smells,
            "quality_gate": p.quality_gate,
            "sonar_report_url": p.sonar_report_url
        }
        for p in pipelines
    ]


@app.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    return calculate_metrics(db)
