"""Chaos lifecycle event producers and adapter observation names."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.events.constants import (
    CHAOS_EXPERIMENT_CREATED,
    CHAOS_FAULT_INJECTED as CHAOS_FAULT_INJECTED_EVENT,
    CHAOS_OBSERVATION_RECORDED,
    CHAOS_RUN_ABORTED,
    CHAOS_RUN_COMPLETED,
    CHAOS_RUN_FAILED,
    CHAOS_RUN_STARTED,
    EXPERIMENT_BENCHMARK_CALCULATED,
)
from app.events.outbox import create_outbox_event


# Adapter-level event names retained for compatibility with Sprint 10B/10C.
CHAOS_FAULT_INJECTED = "chaos.fault.injected"
CHAOS_ADAPTER_FAULT_INJECTED = CHAOS_FAULT_INJECTED
CHAOS_FAULT_REMOVED = "chaos.fault.removed"
CHAOS_FAULT_FAILED = "chaos.fault.failed"
CHAOS_OBSERVATION_SOURCE = "chaos-adapter"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _run_payload(run: Any) -> dict[str, Any]:
    return {
        "chaos_run_id": str(run.id),
        "experiment_id": str(run.experiment_id),
        "service_id": str(run.target_service_id),
        "environment": run.target_environment,
        "failure_injected_at": _iso(run.failure_injected_at),
        "observation_window_end": _iso(run.deadline_at),
        "status": getattr(run.status, "value", run.status),
    }


def create_chaos_run_event(
    *, db: Session, run: Any, event_type: str, extra: dict[str, Any] | None = None
) -> Any:
    payload = _run_payload(run)
    payload.update(extra or {})
    return create_outbox_event(
        db,
        event_type=event_type,
        correlation_id=str(run.id),
        service_id=str(run.target_service_id),
        environment=run.target_environment,
        payload=payload,
    )


def create_chaos_experiment_created_event(*, db: Session, experiment: Any) -> Any:
    return create_outbox_event(
        db,
        event_type=CHAOS_EXPERIMENT_CREATED,
        correlation_id=str(experiment.id),
        service_id=str(experiment.target_service_id),
        environment=experiment.target_environment,
        payload={
            "experiment_id": str(experiment.id),
            "service_id": str(experiment.target_service_id),
            "environment": experiment.target_environment,
            "scenario_type": getattr(
                experiment.scenario_type, "value", experiment.scenario_type
            ),
            "created_at": _iso(experiment.created_at),
        },
    )


def create_chaos_observation_recorded_event(
    *, db: Session, run: Any, observation: Any
) -> Any:
    return create_chaos_run_event(
        db=db,
        run=run,
        event_type=CHAOS_OBSERVATION_RECORDED,
        extra={
            "observation_id": str(observation.id),
            "observation_type": getattr(
                observation.observation_type, "value", observation.observation_type
            ),
            "observed_at": _iso(observation.observed_at),
            "resource_type": observation.resource_type,
            "resource_id": observation.resource_id,
        },
    )


__all__ = [
    "CHAOS_EXPERIMENT_CREATED",
    "CHAOS_RUN_STARTED",
    "CHAOS_FAULT_INJECTED",
    "CHAOS_FAULT_INJECTED_EVENT",
    "CHAOS_OBSERVATION_RECORDED",
    "CHAOS_RUN_COMPLETED",
    "CHAOS_RUN_FAILED",
    "CHAOS_RUN_ABORTED",
    "EXPERIMENT_BENCHMARK_CALCULATED",
    "CHAOS_ADAPTER_FAULT_INJECTED",
    "CHAOS_FAULT_REMOVED",
    "CHAOS_FAULT_FAILED",
    "CHAOS_OBSERVATION_SOURCE",
    "create_chaos_run_event",
    "create_chaos_experiment_created_event",
    "create_chaos_observation_recorded_event",
]