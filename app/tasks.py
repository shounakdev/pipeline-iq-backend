import json
import os
import shutil
from datetime import datetime, timedelta
from typing import Any

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Pipeline, PipelineLog, Analysis
from app.executor import execute_node_pipeline
from app.sonar_service import get_sonar_report
from app.ai_analyzer import analyze_pipeline_report
from app.shared.log_sanitizer import sanitize_log_text

from app.events.constants import PIPELINE_COMPLETED, PIPELINE_FAILED
from app.events.service import record_platform_event

try:
    from app.pipelineiq.security.trivy_scan import (
        run_trivy_filesystem_scan,
        summarize_trivy_report,
    )
except Exception:
    run_trivy_filesystem_scan = None
    summarize_trivy_report = None

try:
    from app.pipelineiq.intelligence.risk_engine import calculate_risk_score
except Exception:
    calculate_risk_score = None


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
        
        ignored_fields = []

        for key, value in fields.items():
            if hasattr(pipeline, key):
                setattr(pipeline, key, value)
            else:
                ignored_fields.append(key)
        
        if ignored_fields:
            print(f"Ignored pipeline fields: {ignored_fields}")

        if hasattr(pipeline, "updated_at"):
            pipeline.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(pipeline)

        return {
            "id": pipeline.id,
            "status": getattr(pipeline, "status", None),
            "error_message": getattr(pipeline, "error_message", None),
            "failure_reason": getattr(pipeline, "failure_reason", None),
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()



def emit_pipeline_terminal_event(pipeline_id: str, event_type: str):
    """
    Record PIPELINE_COMPLETED / PIPELINE_FAILED into the transactional outbox.

    This uses a fresh DB session because the worker helper functions in this file
    also use short-lived sessions.
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

        service_id = getattr(pipeline, "service_id", None)

        event = record_platform_event(
            db,
            event_type=event_type,
            correlation_id=str(pipeline.id),
            service_id=str(service_id) if service_id else None,
            environment=getattr(pipeline, "environment", None) or "staging",
            payload={
                "pipeline_run_id": str(pipeline.id),
                "status": getattr(pipeline, "status", None),
                "stage": getattr(pipeline, "stage", None),
                "risk_score": getattr(pipeline, "risk_score", None),
                "risk_level": getattr(pipeline, "risk_level", None),
                "commit_sha": getattr(pipeline, "commit_sha", None),
                "build_status": getattr(pipeline, "build_status", None),
                "test_status": getattr(pipeline, "test_status", None),
                "sonar_status": getattr(pipeline, "sonar_status", None),
                "trivy_status": getattr(pipeline, "trivy_status", None),
                "failure_reason": getattr(pipeline, "failure_reason", None),
            },
        )

        db.commit()
        return event

    except Exception as exc:
        db.rollback()
        print(f"Failed to record {event_type} for pipeline {pipeline_id}: {exc}")
        return None

    finally:
        db.close()


def add_log_safe(pipeline_id: str, message: str):
    """
    Save a pipeline log using a fresh DB session.

    Behavior:
    - ignore empty messages
    - sanitize logs
    - trim whitespace
    - prevent immediate duplicate logs
    """
    if not message:
        return

    clean_message = sanitize_log_text(str(message).strip())

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
            "status": getattr(pipeline, "status", None),
            "error_message": getattr(pipeline, "error_message", None),
            "failure_reason": getattr(pipeline, "failure_reason", None),
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


def _json_dumps(value: Any):
    return json.dumps(value, default=str)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _workspace_repo_path(execution_result: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Supports the latest executor.py shape:
    - workspace_path points to the temp run folder when cleanup=False
    - repo is inside workspace_path/repo
    """
    workspace_path = execution_result.get("workspace_path") or execution_result.get("run_folder")
    repo_path = execution_result.get("repo_path")

    if not repo_path and workspace_path:
        candidate = os.path.join(workspace_path, "repo")
        if os.path.exists(candidate):
            repo_path = candidate

    return workspace_path, repo_path


def save_execution_result_fields(pipeline_id: str, execution_result: dict[str, Any]):
    """
    Persist fields returned by execute_node_pipeline.

    Important:
    Only save fields that are actually present in execution_result.
    This prevents missing Trivy values from overwriting values already saved
    by stage_fn/update_stage.
    """
    fields = {}

    simple_keys = [
        "commit_sha",
        "commit_message",

        "build_status",
        "test_status",
        "sonar_status",
        "trivy_status",

        "coverage",
        "bugs",
        "vulnerabilities",
        "code_smells",
        "duplicated_lines_density",
        "quality_gate",
        "sonar_report_url",

        "trivy_report",

        "risk_score",
        "risk_level",
        "risk_summary",
        "ai_summary",
    ]

    for key in simple_keys:
        if key in execution_result and execution_result.get(key) is not None:
            fields[key] = execution_result.get(key)

    if "sonar_issues" in execution_result:
        sonar_issues = execution_result.get("sonar_issues") or []
        fields["sonar_issues"] = sonar_issues
        fields["sonar_issues"] = sonar_issues or []

    if "recommendations" in execution_result:
        fields["recommendations"] = execution_result.get("recommendations") or []

    int_keys = [
        "trivy_critical",
        "trivy_high",
        "trivy_medium",
        "trivy_low",
        "trivy_unknown",
        "trivy_total",
    ]

    for key in int_keys:
        if key in execution_result and execution_result.get(key) is not None:
            fields[key] = _safe_int(execution_result.get(key))

    if fields:
        update_pipeline_fields(pipeline_id, **fields)

def save_sonar_metrics(pipeline_id: str):
    """
    Fetch SonarQube report and save important metrics into the pipelines table.

    Build/test failures are hard failures.
    Sonar metrics are saved for intelligence/risk reporting.
    """
    add_log_safe(pipeline_id, "Fetching SonarQube report...")

    sonar_report = get_sonar_report() or {}

    quality_gate = sonar_report.get("quality_gate")
    issues = sonar_report.get("issues", [])

    update_pipeline_fields(
        pipeline_id,
        coverage=sonar_report.get("coverage"),
        bugs=sonar_report.get("bugs"),
        vulnerabilities=sonar_report.get("vulnerabilities"),
        code_smells=sonar_report.get("code_smells"),
        duplicated_lines_density=sonar_report.get("duplicated_lines_density"),
        quality_gate=quality_gate,
        sonar_report_url=sonar_report.get("report_url"),
        sonar_issues=issues or [],
        sonar_status="SUCCESS" if quality_gate != "FAILED" else "FAILED",
    )

    add_log_safe(pipeline_id, f"SonarQube quality gate: {quality_gate}")
    add_log_safe(pipeline_id, f"Coverage: {sonar_report.get('coverage')}")
    add_log_safe(pipeline_id, f"Bugs: {sonar_report.get('bugs')}")
    add_log_safe(pipeline_id, f"Vulnerabilities: {sonar_report.get('vulnerabilities')}")
    add_log_safe(pipeline_id, f"Code smells: {sonar_report.get('code_smells')}")

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

        ai_report = analyze_pipeline_report(
            pipeline_status=pipeline_status,
            execution_logs=execution_logs,
            sonar_report=sonar_report,
        )

        how_to_pass = ai_report.get("how_to_pass", [])

        if isinstance(how_to_pass, list):
            suggestion_text = "\n".join(str(item) for item in how_to_pass)
            recommendations = how_to_pass
        else:
            suggestion_text = str(how_to_pass or "")
            recommendations = [suggestion_text] if suggestion_text else []

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
            analysis.report_json = _json_dumps(ai_report)

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

        update_pipeline_fields(
            pipeline_id,
            ai_summary=ai_report.get("overall_summary"),
            recommendations=recommendations,
        )

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


def run_trivy_scan_for_pipeline(pipeline_id: str, repo_path: str):
    """
    Fallback Trivy runner.

    The latest executor.py already runs Trivy.
    This function is still useful if executor did not return Trivy data.
    """
    if run_trivy_filesystem_scan is None or summarize_trivy_report is None:
        update_pipeline_fields(
            pipeline_id,
            trivy_status="SKIPPED",
        )
        add_log_safe(
            pipeline_id,
            "Trivy scan skipped: Trivy scan module is not available.",
        )
        return None

    add_log_safe(pipeline_id, "Starting Trivy filesystem security scan...")

    try:
        raw_report = run_trivy_filesystem_scan(repo_path)
        summary = summarize_trivy_report(raw_report)

        counts = summary.get("counts", {})
        total = summary.get("total", 0)

        update_pipeline_fields(
            pipeline_id,
            trivy_status="SUCCESS",
            trivy_critical=_safe_int(counts.get("CRITICAL", 0)),
            trivy_high=_safe_int(counts.get("HIGH", 0)),
            trivy_medium=_safe_int(counts.get("MEDIUM", 0)),
            trivy_low=_safe_int(counts.get("LOW", 0)),
            trivy_unknown=_safe_int(counts.get("UNKNOWN", 0)),
            trivy_total=_safe_int(total),
            trivy_report=summary,
        )

        add_log_safe(
            pipeline_id,
            (
                f"Trivy scan completed: {total} findings "
                f"({counts.get('CRITICAL', 0)} critical, "
                f"{counts.get('HIGH', 0)} high, "
                f"{counts.get('MEDIUM', 0)} medium, "
                f"{counts.get('LOW', 0)} low)."
            ),
        )

        return summary

    except Exception as e:
        update_pipeline_fields(
            pipeline_id,
            trivy_status="FAILED",
        )
        add_log_safe(pipeline_id, f"Trivy scan failed: {str(e)}")
        return None


def calculate_release_risk_for_pipeline(pipeline_id: str):
    """
    Calculate Sprint 2E release risk and save it into the pipeline row.
    Uses the Pipeline row because the rest of this worker updates Pipeline.
    """
    if calculate_risk_score is None:
        add_log_safe(
            pipeline_id,
            "Release risk calculation skipped: risk engine is not available.",
        )
        return None

    db = SessionLocal()

    try:
        pipeline = (
            db.query(Pipeline)
            .filter(Pipeline.id == str(pipeline_id))
            .first()
        )

        if not pipeline:
            add_log_safe(
                pipeline_id,
                "Release risk calculation skipped: pipeline not found.",
            )
            return None

        risk_result = calculate_risk_score(pipeline)

        if isinstance(risk_result, dict):
            score = risk_result.get("risk_score")
            level = risk_result.get("risk_level")
            summary = risk_result.get("risk_summary")
            recommendations = risk_result.get("recommendations", [])
        else:
            score, level, summary, recommendations = risk_result

        pipeline.risk_score = score
        pipeline.risk_level = level
        pipeline.risk_summary = summary
        pipeline.recommendations = recommendations

        db.commit()

        add_log_safe(
            pipeline_id,
            f"Release risk calculated: {level} ({score}/100).",
        )

        if summary:
            add_log_safe(pipeline_id, summary)

        return {
            "risk_score": score,
            "risk_level": level,
            "risk_summary": summary,
            "recommendations": recommendations,
        }

    except Exception as e:
        db.rollback()
        add_log_safe(pipeline_id, f"Release risk calculation failed: {str(e)}")
        return None

    finally:
        db.close()


def _progress_for_stage(stage_name: str) -> int:
    progress_map = {
        "RETRYING": 5,
        "STARTED": 5,
        "CLONING": 10,
        "CHECKOUT": 20,
        "INSTALLING": 35,
        "TESTING": 50,
        "BUILDING": 65,
        "SONAR": 75,
        "TRIVY": 85,
        "RISK": 90,
        "AI_SUMMARY": 95,
        "COMPLETED": 100,
        "FAILED": 100,
    }

    return progress_map.get(stage_name, 5)


def mark_stale_running_pipelines_failed(timeout_minutes: int = 45):
    cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)

    db = SessionLocal()

    try:
        stale_pipeline_ids = [
            str(row.id)
            for row in db.query(Pipeline.id)
            .filter(Pipeline.status == "RUNNING")
            .filter(Pipeline.started_at.isnot(None))
            .filter(Pipeline.started_at < cutoff)
            .all()
        ]

    finally:
        db.close()

    for stale_pipeline_id in stale_pipeline_ids:
        update_pipeline_fields(
            stale_pipeline_id,
            status="FAILED",
            stage="FAILED",
            progress=100,
            error_message="Pipeline timed out or worker stopped unexpectedly.",
            failure_reason="Pipeline timed out or worker stopped unexpectedly.",
            finished_at=datetime.utcnow(),
        )

        add_log_safe(
            stale_pipeline_id,
            "Pipeline marked as failed because it was stuck in RUNNING state.",
        )

        emit_pipeline_terminal_event(stale_pipeline_id, PIPELINE_FAILED)

    return len(stale_pipeline_ids)


@celery_app.task(
    name="app.tasks.execute_pipeline_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def execute_pipeline_task(self, pipeline_id: str):
    pipeline_id = str(pipeline_id)
    started_at = datetime.utcnow()
    workspace_path = None

    mark_stale_running_pipelines_failed()

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
            failure_reason=None,
            stage="STARTED",
            build_status="NOT_STARTED",
            test_status="NOT_STARTED",
            sonar_status="NOT_STARTED",
            trivy_status="NOT_STARTED",
            risk_score=None,
            risk_level=None,
            risk_summary=None,
            recommendations=[],
            started_at=started_at,
        )

        add_log_safe(pipeline_id, "Pipeline started.")
        add_log_safe(pipeline_id, f"Repository: {pipeline['repo_url']}")
        add_log_safe(pipeline_id, f"Branch: {pipeline['branch']}")

        def update_stage(stage_name: str, **extra_fields):
            update_payload = {
                "stage": stage_name,
                "progress": _progress_for_stage(stage_name),
            }
            update_payload.update(extra_fields)
            update_pipeline_fields(pipeline_id, **update_payload)

        execution_result = execute_node_pipeline(
            repo_url=pipeline["repo_url"],
            branch=pipeline["branch"],
            stage_fn=update_stage,
            cleanup=False,
        )

        workspace_path, repo_path = _workspace_repo_path(execution_result)

        for log in execution_result.get("logs", []):
            add_log_safe(pipeline_id, log)
            
        add_log_safe(
            pipeline_id,
            "Execution result keys: " + ", ".join(sorted(execution_result.keys())),
            )

        add_log_safe(
            pipeline_id,
            (
                "Persisting execution result: "
                f"critical={execution_result.get('trivy_critical')}, "
                f"trivy_status={execution_result.get('trivy_status')}, "
                f"high={execution_result.get('trivy_high')}, "
                f"medium={execution_result.get('trivy_medium')}, "
                f"total={execution_result.get('trivy_total')}, "
                f"risk_score={execution_result.get('risk_score')}, "
                f"risk_level={execution_result.get('risk_level')}"
            ),
        )

        save_execution_result_fields(pipeline_id, execution_result)

        finished_at = datetime.utcnow()
        duration_seconds = (finished_at - started_at).total_seconds()

        execution_logs = get_pipeline_logs_safe(pipeline_id)

        if execution_result.get("success"):
            update_pipeline_fields(
                pipeline_id,
                status="RUNNING",
                progress=85,
                error_message=None,
                failure_reason=None,
                commit_sha=execution_result.get("commit_sha"),
                commit_message=execution_result.get("commit_message"),
                build_status="SUCCESS",
                test_status="SUCCESS",
            )

            sonar_report = None

            try:
                update_pipeline_fields(
                    pipeline_id,
                    stage="SONAR",
                    progress=75,
                    sonar_status="RUNNING",
                )

                sonar_report = save_sonar_metrics(pipeline_id)

            except Exception as sonar_error:
                update_pipeline_fields(
                    pipeline_id,
                    sonar_status="FAILED",
                )

                add_log_safe(
                    pipeline_id,
                    f"Could not fetch SonarQube report: {str(sonar_error)}",
                )

                sonar_report = {
                    "available": False,
                    "quality_gate": "UNKNOWN",
                    "issues": [],
                }

            # Fallback only: if executor did not return Trivy data, run Trivy here.
            latest_trivy_status = execution_result.get("trivy_status")

            if not latest_trivy_status or latest_trivy_status == "NOT_STARTED":
                if repo_path:
                    update_pipeline_fields(
                        pipeline_id,
                        stage="TRIVY",
                        progress=85,
                        trivy_status="RUNNING",
                    )
                    run_trivy_scan_for_pipeline(pipeline_id, repo_path)
                else:
                    update_pipeline_fields(
                        pipeline_id,
                        trivy_status="SKIPPED",
                    )
                    add_log_safe(
                        pipeline_id,
                        "Trivy scan skipped: repo path not available.",
                    )

            update_pipeline_fields(
                pipeline_id,
                stage="RISK",
                progress=90,
            )

            calculate_release_risk_for_pipeline(pipeline_id)

            update_pipeline_fields(
                pipeline_id,
                stage="AI_SUMMARY",
                progress=95,
            )

            generate_pipeline_ai_report(
                pipeline_id=pipeline_id,
                pipeline_status="SUCCESS",
                execution_logs=get_pipeline_logs_safe(pipeline_id),
                sonar_report=sonar_report,
            )

            update_pipeline_fields(
                pipeline_id,
                status="SUCCESS",
                stage="COMPLETED",
                progress=100,
                error_message=None,
                failure_reason=None,
                finished_at=finished_at,
                duration_seconds=duration_seconds,
            )

            add_log_safe(pipeline_id, "Pipeline completed successfully.")
            emit_pipeline_terminal_event(pipeline_id, PIPELINE_COMPLETED)

            return {
                "success": True,
                "status": "SUCCESS",
                "pipeline_id": pipeline_id,
            }

        error_message = (
            execution_result.get("failure_reason")
            or execution_result.get("error")
            or "Pipeline execution failed"
        )

        update_pipeline_fields(
            pipeline_id,
            status="FAILED",
            stage="FAILED",
            progress=100,
            error_message=error_message,
            failure_reason=error_message,
            commit_sha=execution_result.get("commit_sha"),
            commit_message=execution_result.get("commit_message"),
            build_status=execution_result.get("build_status") or "FAILED",
            test_status=execution_result.get("test_status") or "NOT_STARTED",
            sonar_status=execution_result.get("sonar_status") or "SKIPPED",
            trivy_status=execution_result.get("trivy_status") or "SKIPPED",
            finished_at=finished_at,
            duration_seconds=duration_seconds,
        )

        calculate_release_risk_for_pipeline(pipeline_id)

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

        emit_pipeline_terminal_event(pipeline_id, PIPELINE_FAILED)

        return {
            "success": False,
            "status": "FAILED",
            "pipeline_id": pipeline_id,
            "error": error_message,
        }

    except Exception as e:
        finished_at = datetime.utcnow()
        duration_seconds = (finished_at - started_at).total_seconds()

        current_retry = self.request.retries
        max_retries = self.max_retries or 2

        if current_retry < max_retries:
            retry_number = current_retry + 1

            try:
                update_pipeline_fields(
                    pipeline_id,
                    status="RUNNING",
                    stage="RETRYING",
                    progress=5,
                    error_message=str(e),
                    failure_reason=(
                        f"Worker error. Retrying attempt "
                        f"{retry_number}/{max_retries}: {str(e)}"
                    ),
                )

                add_log_safe(
                    pipeline_id,
                    (
                        "Unexpected worker error occurred. "
                        f"Retrying in 30 seconds "
                        f"({retry_number}/{max_retries}): {str(e)}"
                    ),
                )

            except Exception:
                pass

            raise self.retry(exc=e, countdown=30)

        try:
            update_pipeline_fields(
                pipeline_id,
                status="FAILED",
                stage="FAILED",
                progress=100,
                error_message=str(e),
                failure_reason=str(e),
                finished_at=finished_at,
                duration_seconds=duration_seconds,
            )

            add_log_safe(pipeline_id, f"Pipeline failed after retries: {str(e)}")

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

            emit_pipeline_terminal_event(pipeline_id, PIPELINE_FAILED)

        except Exception:
            pass

        return {
            "success": False,
            "status": "FAILED",
            "pipeline_id": pipeline_id,
            "error": str(e),
        }
        
        
    finally:
        if workspace_path:
            shutil.rmtree(workspace_path, ignore_errors=True)