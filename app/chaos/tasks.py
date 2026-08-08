from uuid import UUID

from app.celery_app import celery_app
from app.chaos.adapters.chaos_mesh_adapter import ChaosMeshAdapter
from app.chaos.adapters.mock_adapter import MockChaosAdapter
from app.chaos.config import ChaosSettings
from app.chaos.reconciliation import reconcile_expired_runs_once
from app.chaos.services.run_service import execute_run
from app.database import SessionLocal


@celery_app.task(name="app.chaos.tasks.execute_chaos_run")
def execute_chaos_run(chaos_run_id: str) -> str:
    settings = ChaosSettings.from_env()

    adapter = (
        MockChaosAdapter()
        if settings.adapter_backend == "mock"
        else ChaosMeshAdapter()
    )

    db = SessionLocal()

    try:
        run = execute_run(
            db=db,
            chaos_run_id=UUID(chaos_run_id),
            adapter=adapter,
            poll_interval_seconds=float(
                settings.watchdog_interval_seconds
            ),
        )
        return run.status.value
    finally:
        db.rollback()
        db.close()


@celery_app.task(name="app.chaos.tasks.reconcile_expired_runs")
def reconcile_expired_runs_task() -> int:
    return reconcile_expired_runs_once()