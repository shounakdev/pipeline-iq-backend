import json
from datetime import datetime

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Pipeline, PipelineLog, Analysis
from app.executor import execute_node_pipeline
from app.sonar_service import get_sonar_report
from app.ai_analyzer import analyze_pipeline_report


def update_pipeline_fields(pipeline_id: str, **fields):
    """
    Open a short-lived DB session, update only the provided pipeline fields,
    commit, and close the session immediately.
    """
    db = SessionLocal()
    try:
        pipeline = (
            db.query(Pipeline)
            .filter(Pipeline.id == str(pipeline_id))
            .first()
        )

        if not pipeline:
            return None

        for key, value in fields.items():
            setattr(pipeline, key, value)

        pipeline.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(pipeline)

        return {
            "id": pipeline.id,
            "status": pipeline.status,
            "error_message": pipeline.error_message,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def add_log_safe(pipeline_id: str, message: str):
    """
    Save a pipeline log using a fresh DB session.

    This keeps your existing behavior:
    - ignore empty messages
    - trim whitespace
    - prevent immediate duplicate logs
    """
    if not message:
        return

    clean_message = str(message).strip()

    if not clean_message:
        return

    db = SessionLocal()
    try:
        last_log = (
            db.query(PipelineLog)
            .filter(PipelineLog.pipeline_id == str(pipeline_id))
            .order_by(PipelineLog.timestamp.desc())
            .first()
        )

        if last_log and last_log.log_text == clean_message:
            return

        log = PipelineLog(
            pipeline_id=str(pipeline_id),
            log_text=clean_message,
            timestamp=datetime.utcnow(),
        )

        db.add(log)
        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def get_pipeline_context(pipeline_id: str):
    """
    Read the pipeline fields needed by the worker, then close the DB session.
    Do not return the SQLAlchemy model object because it becomes detached.
    """
    db = SessionLocal()
    try:
        pipeline = (
            db.query(Pipeline)
            .filter(Pipeline.id == str(pipeline_id))
            .first()
        )

        if not pipeline:
            return None

        return {
            "id": pipeline.id,
            "repo_url": pipeline.repo_url,
            "branch": pipeline.branch or "main",
            "status": pipeline.status,
            "error_message": pipeline.error_message,
        }

    finally:
        db.close()


def get_pipeline_logs_safe(pipeline_id: str):
    """
    Fetch all logs using a fresh DB session.
    """
    db = SessionLocal()
    try:
        pipeline_logs = (
            db.query(PipelineLog)
            .filter(PipelineLog.pipeline_id == str(pipeline_id))
            .order_by(PipelineLog.timestamp.asc())
            .all()
        )

        return [log.log_text for log in pipeline_logs]

    finally:
        db.close()


def save_sonar_metrics(pipeline_id: str):
    """
    Fetch SonarQube report and save important metrics into the pipelines table.

    Important:
    - Code smells do NOT fail the pipeline.
    - Only quality_gate == FAILED should fail the pipeline.
    """
    add_log_safe(pipeline_id, "Fetching SonarQube report...")

    # This can be a network call, so keep it outside any DB session.
    sonar_report = get_sonar_report()

    quality_gate = sonar_report.get("quality_gate")

    update_pipeline_fields(
        pipeline_id,
        coverage=sonar_report.get("coverage"),
        bugs=sonar_report.get("bugs"),
        vulnerabilities=sonar_report.get("vulnerabilities"),
        code_smells=sonar_report.get("code_smells"),
        duplicated_lines_density=sonar_report.get("duplicated_lines_density"),
        quality_gate=quality_gate,
        sonar_report_url=sonar_report.get("report_url"),
        sonar_issues_json=json.dumps(sonar_report.get("issues", []), default=str),
    )

    add_log_safe(pipeline_id, f"SonarQube quality gate: {quality_gate}")
    add_log_safe(pipeline_id, f"Coverage: {sonar_report.get('coverage')}")
    add_log_safe(pipeline_id, f"Bugs: {sonar_report.get('bugs')}")
    add_log_safe(pipeline_id, f"Vulnerabilities: {sonar_report.get('vulnerabilities')}")
    add_log_safe(pipeline_id, f"Code smells: {sonar_report.get('code_smells')}")

    if quality_gate == "FAILED":
        update_pipeline_fields(
            pipeline_id,
            status="FAILED",
            error_message="SonarQube quality gate failed",
        )

        add_log_safe(
            pipeline_id,
            "Pipeline failed because SonarQube quality gate failed.",
        )

    return sonar_report


def generate_pipeline_ai_report(
    pipeline_id: str,
    pipeline_status=None,
    execution_logs=None,
    sonar_report=None,
):
    """
    Generate and save AI analysis using short-lived DB sessions only.
    """
    try:
        if execution_logs is None:
            execution_logs = get_pipeline_logs_safe(pipeline_id)

        if pipeline_status is None:
            pipeline_context = get_pipeline_context(pipeline_id)
            pipeline_status = (
                pipeline_context.get("status")
                if pipeline_context
                else "UNKNOWN"
            )

        if sonar_report is None:
            sonar_report = {
                "available": False,
                "message": "SonarQube report not available for this pipeline run",
                "quality_gate": "UNKNOWN",
                "issues": [],
            }

        # This may call an external AI service later, so keep it outside DB sessions.
        ai_report = analyze_pipeline_report(
            pipeline_status=pipeline_status,
            execution_logs=execution_logs,
            sonar_report=sonar_report,
        )

        how_to_pass = ai_report.get("how_to_pass", [])

        if isinstance(how_to_pass, list):
            suggestion_text = "\n".join(str(item) for item in how_to_pass)
        else:
            suggestion_text = str(how_to_pass or "")

        db = SessionLocal()
        try:
            existing_analysis = (
                db.query(Analysis)
                .filter(Analysis.pipeline_id == str(pipeline_id))
                .first()
            )

            if existing_analysis:
                analysis = existing_analysis
            else:
                analysis = Analysis(pipeline_id=str(pipeline_id))
                db.add(analysis)

            analysis.failure_reason = ai_report.get("overall_summary")
            analysis.confidence = ai_report.get("confidence", 0.7)
            analysis.suggestion = suggestion_text
            analysis.final_status = ai_report.get("final_status")
            analysis.report_json = json.dumps(ai_report, default=str)

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

        add_log_safe(
            pipeline_id,
            f"AI DevOps summary generated: {ai_report.get('final_status')}",
        )

        return ai_report

    except Exception as ai_error:
        try:
            add_log_safe(
                pipeline_id,
                f"AI pipeline report skipped: {str(ai_error)}",
            )
        except Exception:
            pass

        return None


@celery_app.task(name="app.tasks.execute_pipeline_task")
def execute_pipeline_task(pipeline_id: str):
    pipeline_id = str(pipeline_id)
    started_at = datetime.utcnow()

    try:
        pipeline = get_pipeline_context(pipeline_id)

        if not pipeline:
            return {
                "success": False,
                "status": "FAILED",
                "pipeline_id": pipeline_id,
                "error": f"Pipeline with id {pipeline_id} not found",
            }

        update_pipeline_fields(
            pipeline_id,
            status="RUNNING",
            progress=5,
            error_message=None,
            started_at=started_at,
        )

        add_log_safe(pipeline_id, "Pipeline started.")
        add_log_safe(pipeline_id, f"Repository: {pipeline['repo_url']}")
        add_log_safe(pipeline_id, f"Branch: {pipeline['branch']}")
        add_log_safe(pipeline_id, "Starting real Node.js pipeline execution...")

        execution_result = execute_node_pipeline(
            repo_url=pipeline["repo_url"],
            branch=pipeline["branch"],
        )

        for log in execution_result.get("logs", []):
            add_log_safe(pipeline_id, log)

        finished_at = datetime.utcnow()
        duration_seconds = (finished_at - started_at).total_seconds()

        execution_logs = get_pipeline_logs_safe(pipeline_id)

        if execution_result.get("success"):
            update_pipeline_fields(
                pipeline_id,
                status="SUCCESS",
                progress=100,
                error_message=None,
                finished_at=finished_at,
                duration_seconds=duration_seconds,
            )

            add_log_safe(pipeline_id, "Pipeline completed successfully.")

            sonar_report = None

            try:
                sonar_report = save_sonar_metrics(pipeline_id)
            except Exception as sonar_error:
                add_log_safe(
                    pipeline_id,
                    f"Could not fetch SonarQube report: {str(sonar_error)}",
                )

            latest_pipeline = get_pipeline_context(pipeline_id)
            final_status = latest_pipeline["status"] if latest_pipeline else "SUCCESS"

            generate_pipeline_ai_report(
                pipeline_id=pipeline_id,
                pipeline_status=final_status,
                execution_logs=get_pipeline_logs_safe(pipeline_id),
                sonar_report=sonar_report,
            )

            return {
                "success": final_status == "SUCCESS",
                "status": final_status,
                "pipeline_id": pipeline_id,
            }

        error_message = execution_result.get("error") or "Pipeline execution failed"

        update_pipeline_fields(
            pipeline_id,
            status="FAILED",
            progress=100,
            error_message=error_message,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
        )

        add_log_safe(pipeline_id, f"Pipeline failed: {error_message}")

        generate_pipeline_ai_report(
            pipeline_id=pipeline_id,
            pipeline_status="FAILED",
            execution_logs=execution_logs,
            sonar_report={
                "available": False,
                "quality_gate": "UNKNOWN",
                "issues": [],
            },
        )

        return {
            "success": False,
            "status": "FAILED",
            "pipeline_id": pipeline_id,
            "error": error_message,
        }

    except Exception as e:
        finished_at = datetime.utcnow()
        duration_seconds = (finished_at - started_at).total_seconds()

        try:
            update_pipeline_fields(
                pipeline_id,
                status="FAILED",
                progress=100,
                error_message=str(e),
                finished_at=finished_at,
                duration_seconds=duration_seconds,
            )

            add_log_safe(pipeline_id, f"Pipeline failed: {str(e)}")

            generate_pipeline_ai_report(
                pipeline_id=pipeline_id,
                pipeline_status="FAILED",
                execution_logs=get_pipeline_logs_safe(pipeline_id),
                sonar_report={
                    "available": False,
                    "quality_gate": "UNKNOWN",
                    "issues": [],
                },
            )

        except Exception:
            pass

        return {
            "success": False,
            "status": "FAILED",
            "pipeline_id": pipeline_id,
            "error": str(e),
        }