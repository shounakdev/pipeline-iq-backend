"""Post-remediation recovery verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.incidents import repository as incident_repository
from app.incidents.enums import IncidentStatus
from app.models import (
    RecoveryVerification,
    RecoveryVerificationStatus,
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationRecommendation,
    ServiceHealthSnapshot,
    ServiceHealthStatus,
)
from app.remediation import repository
from app.remediation.events import (
    create_recovery_failed_event,
    create_recovery_verified_event,
)


MAX_RECOVERED_ERROR_RATE = 1.0
MAX_RECOVERED_P95_LATENCY_MS = 500.0


class RemediationVerificationError(Exception):
    """Base exception for recovery verification."""


class RemediationNotFoundError(
    RemediationVerificationError,
):
    """Raised when the recommendation does not exist."""


class RemediationExecutionNotFoundError(
    RemediationVerificationError,
):
    """Raised when no execution exists."""


class RemediationExecutionIncompleteError(
    RemediationVerificationError,
):
    """Raised when execution did not succeed."""


class RecoveryHealthSnapshotMissingError(
    RemediationVerificationError,
):
    """Raised when post-execution health is unavailable."""


@dataclass(frozen=True)
class RecoveryVerificationResult:
    recommendation: RemediationRecommendation
    execution: RemediationExecution
    verification: RecoveryVerification
    recovered: bool


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _number_at_most(
    value: Any,
    maximum: float,
) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False

    return 0.0 <= number <= maximum


def _pods_are_healthy(
    snapshot: ServiceHealthSnapshot,
) -> bool:
    replica_count = snapshot.replica_count
    available_replicas = (
        snapshot.available_replicas
    )

    if (
        replica_count is None
        or available_replicas is None
    ):
        return False

    return (
        replica_count > 0
        and available_replicas
        >= replica_count
    )


def _restart_loop_is_absent(
    *,
    current: ServiceHealthSnapshot,
    previous: ServiceHealthSnapshot | None,
) -> bool:
    current_restarts = current.pod_restart_count

    if current_restarts is None:
        return False

    if previous is None:
        return current_restarts == 0

    previous_restarts = previous.pod_restart_count

    if previous_restarts is None:
        return current_restarts == 0

    return current_restarts <= previous_restarts


def _previous_health_snapshot(
    *,
    current: ServiceHealthSnapshot,
    history: list[ServiceHealthSnapshot],
) -> ServiceHealthSnapshot | None:
    for snapshot in history:
        if snapshot.id != current.id:
            return snapshot

    return None


def _metrics_snapshot(
    *,
    health: ServiceHealthSnapshot,
    previous: ServiceHealthSnapshot | None,
) -> dict[str, Any]:
    return {
        "health_snapshot_id": str(health.id),
        "observed_at": (
            health.created_at.isoformat()
            if health.created_at
            else None
        ),
        "status": _enum_value(health.status),
        "error_rate": health.error_rate,
        "p95_latency_ms": health.latency_ms,
        "pod_restart_count": (
            health.pod_restart_count
        ),
        "previous_pod_restart_count": (
            previous.pod_restart_count
            if previous is not None
            else None
        ),
        "replica_count": health.replica_count,
        "available_replicas": (
            health.available_replicas
        ),
        "thresholds": {
            "maximum_error_rate": (
                MAX_RECOVERED_ERROR_RATE
            ),
            "maximum_p95_latency_ms": (
                MAX_RECOVERED_P95_LATENCY_MS
            ),
        },
    }


def verify_remediation_recovery(
    *,
    db: Session,
    remediation_id: UUID,
    now: datetime | None = None,
) -> RecoveryVerificationResult:
    try:
        recommendation = (
            repository.get_remediation_by_id(
                db,
                remediation_id,
                for_update=True,
            )
        )

        if recommendation is None:
            raise RemediationNotFoundError(
                "Remediation recommendation was not found"
            )

        execution = (
            repository
            .get_execution_by_remediation_id(
                db,
                remediation_id,
            )
        )

        if execution is None:
            raise RemediationExecutionNotFoundError(
                "Remediation execution was not found"
            )

        existing_verification = (
            repository
            .get_recovery_verification_for_execution(
                db,
                execution.id,
            )
        )

        if existing_verification is not None:
            return RecoveryVerificationResult(
                recommendation=recommendation,
                execution=execution,
                verification=existing_verification,
                recovered=(
                    existing_verification
                    .verification_status
                    == RecoveryVerificationStatus.VERIFIED
                ),
            )

        if (
            execution.execution_status
            != RemediationExecutionStatus.SUCCEEDED
            or execution.completed_at is None
        ):
            raise RemediationExecutionIncompleteError(
                "Only a successful completed execution "
                "can be verified"
            )

        health = (
            repository.get_latest_service_health_after(
                db,
                service_id=str(
                    recommendation.service_id,
                ),
                environment=(
                    recommendation.environment
                ),
                observed_after=execution.completed_at,
            )
        )

        if health is None:
            raise RecoveryHealthSnapshotMissingError(
                "No post-execution health snapshot "
                "is available"
            )

        health_history = (
            repository.get_service_health_history(
                db,
                service_id=str(
                    recommendation.service_id,
                ),
                environment=(
                    recommendation.environment
                ),
                limit=5,
            )
        )

        previous_health = _previous_health_snapshot(
            current=health,
            history=health_history,
        )

        error_rate_recovered = _number_at_most(
            health.error_rate,
            MAX_RECOVERED_ERROR_RATE,
        )
        latency_recovered = _number_at_most(
            health.latency_ms,
            MAX_RECOVERED_P95_LATENCY_MS,
        )
        pods_healthy = _pods_are_healthy(health)
        restart_loop_absent = (
            _restart_loop_is_absent(
                current=health,
                previous=previous_health,
            )
        )
        availability_restored = (
            _enum_value(health.status)
            == ServiceHealthStatus.HEALTHY.value
        )

        recovered = all(
            (
                error_rate_recovered,
                latency_recovered,
                pods_healthy,
                restart_loop_absent,
                availability_restored,
            )
        )

        verification_status = (
            RecoveryVerificationStatus.VERIFIED
            if recovered
            else RecoveryVerificationStatus.FAILED
        )

        verified_at = (
            now or datetime.now(timezone.utc)
        )

        verification = (
            repository.create_recovery_verification(
                db,
                remediation=recommendation,
                execution=execution,
                verification_status=(
                    verification_status
                ),
                error_rate_recovered=(
                    error_rate_recovered
                ),
                latency_recovered=(
                    latency_recovered
                ),
                pods_healthy=pods_healthy,
                restart_loop_absent=(
                    restart_loop_absent
                ),
                availability_restored=(
                    availability_restored
                ),
                metrics_snapshot=_metrics_snapshot(
                    health=health,
                    previous=previous_health,
                ),
                verified_at=verified_at,
            )
        )

        incident = repository.get_incident_by_id(
            db,
            recommendation.incident_id,
            for_update=True,
        )

        if incident is None:
            raise RemediationVerificationError(
                "Incident linked to remediation "
                "was not found"
            )

        remediation_summary = (
            "Service recovery verified after "
            f"{recommendation.action_type.value}."
            if recovered
            else
            "Service remained unhealthy after "
            f"{recommendation.action_type.value}."
        )

        if recovered:
            incident_repository.update_incident_status(
                db,
                incident,
                status=IncidentStatus.RESOLVED,
                resolved_at=verified_at,
                resolution_summary=(
                    "Recovery verified after "
                    "remediation."
                ),
                remediation_summary=(
                    remediation_summary
                ),
            )

            create_recovery_verified_event(
                db=db,
                recommendation=recommendation,
                execution=execution,
                verification=verification,
            )
        else:
            incident_repository.update_incident_status(
                db,
                incident,
                status=(
                    IncidentStatus.FAILED_RECOVERY
                ),
                resolved_at=None,
                remediation_summary=(
                    remediation_summary
                ),
            )

            create_recovery_failed_event(
                db=db,
                recommendation=recommendation,
                execution=execution,
                verification=verification,
            )

        db.commit()
        db.refresh(recommendation)
        db.refresh(execution)
        db.refresh(verification)
        db.refresh(incident)

        return RecoveryVerificationResult(
            recommendation=recommendation,
            execution=execution,
            verification=verification,
            recovered=recovered,
        )

    except Exception:
        db.rollback()
        raise
