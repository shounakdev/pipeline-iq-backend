from datetime import datetime, timedelta

from app.models import Pipeline


def mark_stale_running_pipelines_failed(db, max_age_minutes: int = 60) -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)

    stale_pipelines = (
        db.query(Pipeline)
        .filter(Pipeline.status == "RUNNING")
        .filter(Pipeline.updated_at < cutoff)
        .all()
    )

    for pipeline in stale_pipelines:
        pipeline.status = "FAILED"
        pipeline.stage = "FAILED"
        pipeline.failure_reason = (
            "Pipeline was marked failed because it was stale in RUNNING state."
        )
        pipeline.error_message = "Stale RUNNING pipeline timeout."

    db.commit()

    return len(stale_pipelines)
