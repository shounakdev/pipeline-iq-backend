"""Durable, idempotent observations for the chaos correlation timeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.chaos import repository
from app.chaos.events import create_chaos_observation_recorded_event
from app.models import ChaosObservation, ChaosObservationType, ChaosRun


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_inside_observation_window(
    run: ChaosRun,
    observed_at: datetime,
) -> bool:
    """Return whether an event can have been caused by this run."""
    if run.failure_injected_at is None:
        return False
    timestamp = as_utc(observed_at)
    return (
        as_utc(run.failure_injected_at) <= timestamp
        and timestamp <= as_utc(run.deadline_at)
    )


def record_observation(
    db: Session,
    *,
    run: ChaosRun,
    observation_type: ChaosObservationType,
    observed_at: datetime,
    source: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    singleton: bool = False,
) -> ChaosObservation | None:
    """Record one timeline item without duplicating redelivered events.

    Singleton observations (notably alerts and incidents) retain the earliest
    matching event even when Kafka delivers records out of order.
    """
    if (
        observation_type != ChaosObservationType.FAILURE_INJECTED
        and not is_inside_observation_window(run, observed_at)
    ):
        return None

    existing = repository.list_observations_for_run(
        db,
        run.id,
        observation_type=observation_type,
    )
    if resource_id is not None:
        duplicate = next(
            (
                item
                for item in existing
                if item.resource_type == resource_type
                and item.resource_id == resource_id
            ),
            None,
        )
        if duplicate is not None:
            return duplicate

    if singleton and existing:
        earliest = existing[0]
        if as_utc(earliest.observed_at) <= as_utc(observed_at):
            return earliest
        earliest.observed_at = observed_at
        earliest.source = source
        earliest.resource_type = resource_type
        earliest.resource_id = resource_id
        earliest.details = details or {}
        observation = earliest
    else:
        observation = repository.create_observation(
            db,
            chaos_run_id=run.id,
            observation_type=observation_type,
            source=source,
            observed_at=observed_at,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )

    create_chaos_observation_recorded_event(
        db=db,
        run=run,
        observation=observation,
    )
    return observation