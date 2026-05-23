import json
from datetime import datetime

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Pipeline, PipelineLog, Analysis
from app.executor import execute_node_pipeline
from app.sonar_service import get_sonar_report
from app.ai_analyzer import analyze_pipeline_report


_UNSET = object()


def add_log(db, pipeline_id: str, message: str):
    if not message:
        return

    clean_message = str(message).strip()

    if not clean_message:
        return

    # Prevent immediate duplicate DB logs
    last_log = (
        db.query(PipelineLog)
        .filter(PipelineLog.pipeline_id == pipeline_id)
        .order_by(PipelineLog.timestamp.desc())
        .first()
    )

    if last_log and last_log.log_text == clean_message:
        return

    log = PipelineLog(
        pipeline_id=pipeline_id,
        log_text=clean_message,
        timestamp=datetime.utcnow(),
    )

    db.add(log)
    db.commit()


def update_pipeline(
    db,
    pipeline,
    status=_UNSET,
    progress=_UNSET,
    error_message=_UNSET,
    started_at=_UNSET,
    finished_at=_UNSET,
    duration_seconds=_UNSET,
):
    if status is not _UNSET:
        pipeline.status = status

    if progress is not _UNSET:
        pipeline.progress = progress

    if error_message is not _UNSET:
        pipeline.error_message = error_message

    if started_at is not _UNSET:
        pipeline.started_at = started_at

    if finished_at is not _UNSET:
        pipeline.finished_at = finished_at

    if duration_seconds is not _UNSET:
        pipeline.duration_seconds = duration_seconds

    pipeline.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(pipeline)


def get_pipeline_logs(db, pipeline_id: str):
    pipeline_logs = (
        db.query(PipelineLog)
        .filter(PipelineLog.pipeline_id == pipeline_id)
        .order_by(PipelineLog.timestamp.asc())
        .all()
    )

    return [log.log_text for log in pipeline_logs]


def save_sonar_metrics(db, pipeline):
    """
    Fetch SonarQube report and save important metrics into pipelines table.

    Important:
    - Code smells do NOT fail the pipeline.
    - Only quality_gate == FAILED should fail the pipeline.
    """

    add_log(db, pipeline.id, "Fetching SonarQube report...")

    sonar_report = get_sonar_report()

    pipeline.coverage = sonar_report.get("coverage")
    pipeline.bugs = sonar_report.get("bugs")
    pipeline.vulnerabilities = sonar_report.get("vulnerabilities")
    pipeline.code_smells = sonar_report.get("code_smells")
    pipeline.duplicated_lines_density = sonar_report.get("duplicated_lines_density")
    pipeline.quality_gate = sonar_report.get("quality_gate")
    pipeline.sonar_report_url = sonar_report.get("report_url")
    pipeline.sonar_issues_json = json.dumps(sonar_report.get("issues", []))
    pipeline.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(pipeline)

    add_log(db, pipeline.id, f"SonarQube quality gate: {pipeline.quality_gate}")
    add_log(db, pipeline.id, f"Coverage: {pipeline.coverage}")
    add_log(db, pipeline.id, f"Bugs: {pipeline.bugs}")
    add_log(db, pipeline.id, f"Vulnerabilities: {pipeline.vulnerabilities}")
    add_log(db, pipeline.id, f"Code smells: {pipeline.code_smells}")

    if pipeline.quality_gate == "FAILED":
        pipeline.status = "FAILED"
        pipeline.error_message = "SonarQube quality gate failed"
        pipeline.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(pipeline)

        add_log(
            db,
            pipeline.id,
            "Pipeline failed because SonarQube quality gate failed.",
        )

    return sonar_report


def generate_pipeline_ai_report(db, pipeline, execution_logs=None, sonar_report=None):
    try:
        if execution_logs is None:
            execution_logs = get_pipeline_logs(db, pipeline.id)

        if sonar_report is None:
            sonar_report = {
                "available": False,
                "message": "SonarQube report not available for this pipeline run",
                "quality_gate": "UNKNOWN",
                "issues": [],
            }

        ai_report = analyze_pipeline_report(
            pipeline_status=pipeline.status,
            execution_logs=execution_logs,
            sonar_report=sonar_report,
        )

        how_to_pass = ai_report.get("how_to_pass", [])

        if isinstance(how_to_pass, list):
            suggestion_text = "\n".join(str(item) for item in how_to_pass)
        else:
            suggestion_text = str(how_to_pass or "")

        existing_analysis = (
            db.query(Analysis)
            .filter(Analysis.pipeline_id == pipeline.id)
            .first()
        )

        if existing_analysis:
            analysis = existing_analysis
        else:
            analysis = Analysis(pipeline_id=pipeline.id)
            db.add(analysis)

        analysis.failure_reason = ai_report.get("overall_summary")
        analysis.confidence = ai_report.get("confidence", 0.7)
        analysis.suggestion = suggestion_text
        analysis.final_status = ai_report.get("final_status")
        analysis.report_json = json.dumps(ai_report, default=str)

        db.commit()

        add_log(
            db,
            pipeline.id,
            f"AI DevOps summary generated: {ai_report.get('final_status')}",
        )

        return ai_report

    except Exception as ai_error:
        db.rollback()

        add_log(
            db,
            pipeline.id,
            f"AI pipeline report skipped: {str(ai_error)}",
        )

        return None


@celery_app.task(name="app.tasks.execute_pipeline_task")
def execute_pipeline_task(pipeline_id: str):
    db = SessionLocal()
    started_at = datetime.utcnow()
    pipeline = None

    try:
        pipeline = (
            db.query(Pipeline)
            .filter(Pipeline.id == str(pipeline_id))
            .first()
        )

        if not pipeline:
            return {
                "success": False,
                "status": "FAILED",
                "error": f"Pipeline with id {pipeline_id} not found",
            }

        update_pipeline(
            db=db,
            pipeline=pipeline,
            status="RUNNING",
            progress=5,
            error_message=None,
            started_at=started_at,
        )

        add_log(db, pipeline.id, "Pipeline started.")
        add_log(db, pipeline.id, f"Repository: {pipeline.repo_url}")
        add_log(db, pipeline.id, f"Branch: {pipeline.branch or 'main'}")

        execution_result = execute_node_pipeline(
            repo_url=pipeline.repo_url,
            branch=pipeline.branch or "main",
        )

        for log in execution_result.get("logs", []):
            add_log(db, pipeline.id, log)

        finished_at = datetime.utcnow()
        duration_seconds = (finished_at - started_at).total_seconds()

        execution_logs = execution_result.get("logs") or get_pipeline_logs(
            db,
            pipeline.id,
        )

        if execution_result.get("success"):
            update_pipeline(
                db=db,
                pipeline=pipeline,
                status="SUCCESS",
                progress=100,
                error_message=None,
                finished_at=finished_at,
                duration_seconds=duration_seconds,
            )

            add_log(db, pipeline.id, "Pipeline completed successfully.")

            sonar_report = None

            try:
                sonar_report = save_sonar_metrics(db, pipeline)
            except Exception as sonar_error:
                add_log(
                    db,
                    pipeline.id,
                    f"Could not fetch SonarQube report: {str(sonar_error)}",
                )

            execution_logs = get_pipeline_logs(db, pipeline.id)
            generate_pipeline_ai_report(
                db =db,
                pipeline=pipeline,
                execution_logs=execution_logs,
                sonar_report=sonar_report,
            )
            # If SonarQube quality gate failed, stop here.
            # Do not fail only because code smells > 0.
            if pipeline.status == "FAILED":
                return {
                    "success": False,
                    "status": "FAILED",
                    "pipeline_id": pipeline.id,
                    "error": pipeline.error_message,
                }
            



            return {
                "success": True,
                "status": "SUCCESS",
                "pipeline_id": pipeline.id,
            }

        error_message = (
            execution_result.get("error")
            or execution_result.get("failure_reason")
            or "Pipeline failed"
        )

        update_pipeline(
            db=db,
            pipeline=pipeline,
            status="FAILED",
            progress=100,
            error_message=error_message,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
        )

        add_log(db, pipeline.id, f"Pipeline failed: {error_message}")
        
        execution_logs = get_pipeline_logs(db, pipeline.id)

        generate_pipeline_ai_report(
            db=db,
            pipeline=pipeline,
            execution_logs=execution_logs,
        )

        return {
            "success": False,
            "status": "FAILED",
            "pipeline_id": pipeline.id,
            "error": error_message,
        }

    except Exception as error:
        finished_at = datetime.utcnow()
        duration_seconds = (finished_at - started_at).total_seconds()

        try:
            if pipeline is None:
                pipeline = (
                    db.query(Pipeline)
                    .filter(Pipeline.id == str(pipeline_id))
                    .first()
                )

            if pipeline:
                update_pipeline(
                    db=db,
                    pipeline=pipeline,
                    status="FAILED",
                    progress=100,
                    error_message=str(error),
                    finished_at=finished_at,
                    duration_seconds=duration_seconds,
                )

                add_log(
                    db,
                    pipeline.id,
                    f"Unexpected worker error: {str(error)}",
                )

                execution_logs = get_pipeline_logs(db, pipeline.id)

                generate_pipeline_ai_report(
                    db=db,
                    pipeline=pipeline,
                    execution_logs=execution_logs,
                )

        except Exception:
            pass

        return {
            "success": False,
            "status": "FAILED",
            "pipeline_id": str(pipeline_id),
            "error": str(error),
        }

    finally:
        db.close()
