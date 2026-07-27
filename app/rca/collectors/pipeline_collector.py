from sqlalchemy.orm import Session

from app.models import PipelineRun


def collect_pipeline_evidence(db: Session, pipeline_run_id) -> dict:
    if not pipeline_run_id:
        return {
            "status": "NO_DATA",
            "reason": "No pipeline_run_id available from deployment evidence",
        }

    pipeline_run = db.query(PipelineRun).filter(PipelineRun.id == pipeline_run_id).first()

    if not pipeline_run:
        return {
            "status": "NO_DATA",
            "reason": "Pipeline run not found",
            "pipeline_run_id": str(pipeline_run_id),
        }

    pipeline_status = _enum_value(getattr(pipeline_run, "status", None))

    return {
        "status": "COLLECTED",
        "pipeline_run_id": str(pipeline_run.id),
        "pipeline_status": pipeline_status,
        "quality_gate": _enum_value(getattr(pipeline_run, "quality_gate", None)),
        "test_result": _enum_value(getattr(pipeline_run, "test_status", None)),
        "security_scan_result": _enum_value(getattr(pipeline_run, "trivy_status", None)),
        "release_risk_score": getattr(pipeline_run, "risk_score", None),
        "failed_stage": (
            getattr(pipeline_run, "stage", None)
            if pipeline_status == "FAILED"
            else None
        ),
        "high_severity_findings": getattr(pipeline_run, "trivy_high", None),
        "medium_severity_findings": getattr(pipeline_run, "trivy_medium", None),
        "completed_at": getattr(pipeline_run, "finished_at", None),
        "interpretation_note": "A passed pipeline is not proof that the release is healthy.",
    }


def _enum_value(value):
    if value is None:
        return None

    return getattr(value, "value", value)