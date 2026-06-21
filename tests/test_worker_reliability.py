from datetime import datetime, timedelta
import uuid

from app.models import Pipeline
from app.pipelineiq.reliability.stale_runs import mark_stale_running_pipelines_failed


def test_stale_running_pipeline_gets_marked_failed(db):
    stale_pipeline = Pipeline(
        id=str(uuid.uuid4()),
        repo_url="https://github.com/shounakdev/meetup",
        branch="cicd_test",
        status="RUNNING",
        stage="BUILD",
        progress=45,
        updated_at=datetime.utcnow() - timedelta(hours=3),
    )

    healthy_pipeline = Pipeline(
        id=str(uuid.uuid4()),
        repo_url="https://github.com/shounakdev/meetup",
        branch="cicd_test",
        status="RUNNING",
        stage="TEST",
        progress=60,
        updated_at=datetime.utcnow(),
    )

    db.add(stale_pipeline)
    db.add(healthy_pipeline)
    db.commit()

    marked_count = mark_stale_running_pipelines_failed(db, max_age_minutes=60)

    db.refresh(stale_pipeline)
    db.refresh(healthy_pipeline)

    assert marked_count == 1

    assert stale_pipeline.status == "FAILED"
    assert stale_pipeline.stage == "FAILED"
    assert stale_pipeline.failure_reason is not None

    assert healthy_pipeline.status == "RUNNING"
    assert healthy_pipeline.stage == "TEST"
