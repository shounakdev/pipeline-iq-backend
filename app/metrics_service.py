from sqlalchemy.orm import Session
from app.models import Pipeline, Analysis


def calculate_metrics(db: Session):
    pipelines = db.query(Pipeline).all()

    total = len(pipelines)

    if total == 0:
        return {
            "total_pipelines": 0,
            "success_rate": 0,
            "failure_rate": 0,
            "avg_pipeline_time_seconds": 0,
            "mttr_seconds": 0,
            "common_failure_reasons": []
        }

    success_count = len([p for p in pipelines if p.status == "SUCCESS"])
    failed_pipelines = [p for p in pipelines if p.status == "FAILED"]

    durations = [
        p.duration_seconds
        for p in pipelines
        if p.duration_seconds is not None
    ]

    avg_time = sum(durations) / len(durations) if durations else 0

    failed_durations = [
        p.duration_seconds
        for p in failed_pipelines
        if p.duration_seconds is not None
    ]

    mttr = sum(failed_durations) / len(failed_durations) if failed_durations else 0

    analyses = db.query(Analysis).all()

    reasons = {}

    for analysis in analyses:
        reason = analysis.failure_reason or "Unknown"
        reasons[reason] = reasons.get(reason, 0) + 1

    common_failure_reasons = [
        {"reason": reason, "count": count}
        for reason, count in reasons.items()
    ]

    return {
        "total_pipelines": total,
        "success_rate": round((success_count / total) * 100, 2),
        "failure_rate": round(((total - success_count) / total) * 100, 2),
        "avg_pipeline_time_seconds": round(avg_time, 2),
        "mttr_seconds": round(mttr, 2),
        "common_failure_reasons": common_failure_reasons
    }