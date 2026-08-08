"""Deadline watchdog and restart reconciliation."""

from datetime import datetime, timezone

from app.chaos import repository
from app.chaos.config import ChaosSettings
from app.chaos.adapters.chaos_mesh_adapter import ChaosMeshAdapter
from app.chaos.service import cleanup_chaos_run
from app.database import SessionLocal


def reconcile_expired_runs_once(
    *,
    adapter: ChaosMeshAdapter | None = None,
    settings: ChaosSettings | None = None,
) -> int:
    settings = settings or ChaosSettings.from_env()
    if not settings.enabled:
        return 0
    adapter = adapter or ChaosMeshAdapter()
    db = SessionLocal()
    cleaned = 0
    try:
        runs = repository.list_active_runs(
            db,
            deadline_before=datetime.now(timezone.utc),
            for_update=True,
        )
        for run in runs:
            cleanup_chaos_run(
                db=db,
                chaos_run=run,
                adapter=adapter,
                reason="deadline exceeded",
                aborted=True,
            )
            cleaned += 1
        return cleaned
    finally:
        db.rollback()
        db.close()


def reconcile_startup_runs_once() -> int:
    return reconcile_expired_runs_once()

