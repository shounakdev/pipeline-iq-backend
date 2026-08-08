"""Background orchestration for the complete chaos-run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Callable, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chaos import repository
from app.chaos.adapters.base import BaseChaosAdapter
from app.chaos.events import CHAOS_OBSERVATION_SOURCE
from app.chaos.services.benchmark_service import calculate_benchmark
from app.chaos.exceptions import (
    ChaosRunNotFoundError,
    ChaosRunTimeoutError,
)
from app.chaos.kubernetes_adapter import build_podchaos_manifest
from app.models import (
    ChaosObservationType,
    ChaosRun,
    ChaosRunStatus,
    Incident,
    RCAReport,
    RCAReportStatus,
    RecoveryVerification,
    RecoveryVerificationStatus,
    ReliabilityAlert,
    RemediationApproval,
    RemediationExecution,
    RemediationRecommendation,
    ServiceHealthSnapshot,
    ServiceHealthStatus,
)


@dataclass(frozen=True)
class ObservationResult:
    recovered: bool = False


class PlatformIQObserver(Protocol):
    """Boundary around PlatformIQ data queried by the runner."""

    def capture_baseline(
        self,
        db: Session,
        run: ChaosRun,
    ) -> dict[str, Any]: ...

    def observe(
        self,
        db: Session,
        run: ChaosRun,
        baseline: dict[str, Any],
    ) -> ObservationResult: ...


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _injected_at(resource: dict[str, Any]) -> datetime:
    raw = resource.get("injected_at")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return _as_utc(parsed)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class DatabasePlatformIQObserver:
    """Observe artifacts produced by existing PlatformIQ pipelines.

    This service only reads remediation state. It never creates an approval or
    starts remediation, preserving Sprint 9's human approval boundary.
    """

    def capture_baseline(
        self,
        db: Session,
        run: ChaosRun,
    ) -> dict[str, Any]:
        snapshot = db.scalars(
            select(ServiceHealthSnapshot)
            .where(
                ServiceHealthSnapshot.service_id == run.target_service_id,
                ServiceHealthSnapshot.environment == run.target_environment,
            )
            .order_by(ServiceHealthSnapshot.created_at.desc())
            .limit(1)
        ).first()
        if snapshot is None:
            return {"captured_at": datetime.now(timezone.utc).isoformat()}
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_id": str(snapshot.id),
            "status": snapshot.status.value,
            "latency_ms": snapshot.latency_ms,
            "error_rate": snapshot.error_rate,
            "available_replicas": snapshot.available_replicas,
        }

    def _record_once(
        self,
        db: Session,
        run: ChaosRun,
        observation_type: ChaosObservationType,
        observed_at: datetime,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any],
    ) -> None:
        existing = repository.list_observations_for_run(
            db, run.id, observation_type=observation_type
        )
        if any(item.resource_id == resource_id for item in existing):
            return
        repository.create_observation(
            db,
            chaos_run_id=run.id,
            observation_type=observation_type,
            source="platformiq",
            observed_at=observed_at,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )

    def observe(
        self,
        db: Session,
        run: ChaosRun,
        baseline: dict[str, Any],
    ) -> ObservationResult:
        del baseline
        injected_at = run.failure_injected_at or run.started_at
        if injected_at is None:
            return ObservationResult()

        snapshots = list(db.scalars(
            select(ServiceHealthSnapshot).where(
                ServiceHealthSnapshot.service_id == run.target_service_id,
                ServiceHealthSnapshot.environment == run.target_environment,
                ServiceHealthSnapshot.created_at >= injected_at,
            ).order_by(ServiceHealthSnapshot.created_at.asc())
        ).all())
        unhealthy_seen = False
        recovered = False
        for snapshot in snapshots:
            if snapshot.status in {
                ServiceHealthStatus.DEGRADED,
                ServiceHealthStatus.UNHEALTHY,
            }:
                unhealthy_seen = True
                self._record_once(
                    db, run, ChaosObservationType.TELEMETRY_ANOMALY,
                    snapshot.created_at, "ServiceHealthSnapshot",
                    str(snapshot.id), {"status": snapshot.status.value},
                )
            elif unhealthy_seen and snapshot.status == ServiceHealthStatus.HEALTHY:
                recovered = True
                self._record_once(
                    db, run, ChaosObservationType.RECOVERY_COMPLETED,
                    snapshot.created_at, "ServiceHealthSnapshot",
                    str(snapshot.id), {"status": snapshot.status.value},
                )

        alert = db.scalars(
            select(ReliabilityAlert).where(
                ReliabilityAlert.service_id == run.target_service_id,
                ReliabilityAlert.created_at >= injected_at,
            ).order_by(ReliabilityAlert.created_at.asc()).limit(1)
        ).first()
        if alert is not None:
            self._record_once(
                db, run, ChaosObservationType.ALERT_CREATED,
                alert.created_at, "ReliabilityAlert", str(alert.id),
                {"status": alert.status.value},
            )

        incident = db.scalars(
            select(Incident).where(
                Incident.primary_service_id == run.target_service_id,
                Incident.environment == run.target_environment,
                Incident.detected_at >= injected_at,
            ).order_by(Incident.detected_at.asc()).limit(1)
        ).first()
        if incident is not None:
            repository.link_run_artifacts(db, chaos_run=run, incident_id=incident.id)
            self._record_once(
                db, run, ChaosObservationType.INCIDENT_CREATED,
                incident.detected_at, "Incident", str(incident.id),
                {"incident_number": incident.incident_number},
            )
            self._observe_incident_artifacts(db, run, incident.id)

        verification = (
            db.get(RecoveryVerification, run.recovery_verification_id)
            if run.recovery_verification_id else None
        )
        if verification is not None and (
            verification.verification_status == RecoveryVerificationStatus.VERIFIED
        ):
            recovered = True
            observed_at = verification.verified_at or verification.created_at
            self._record_once(
                db, run, ChaosObservationType.RECOVERY_COMPLETED,
                observed_at, "RecoveryVerification", str(verification.id),
                {"status": verification.verification_status.value},
            )
        db.commit()
        db.refresh(run)
        return ObservationResult(recovered=recovered)

    def _observe_incident_artifacts(
        self,
        db: Session,
        run: ChaosRun,
        incident_id: UUID,
    ) -> None:
        report = db.scalars(
            select(RCAReport).where(
                RCAReport.incident_id == incident_id,
                RCAReport.status == RCAReportStatus.COMPLETED,
            ).order_by(RCAReport.generated_at.asc()).limit(1)
        ).first()
        if report is not None:
            observed_at = report.generated_at or report.updated_at
            repository.link_run_artifacts(db, chaos_run=run, rca_report_id=report.id)
            self._record_once(
                db, run, ChaosObservationType.RCA_COMPLETED, observed_at,
                "RCAReport", str(report.id),
                {"probable_root_cause": report.probable_root_cause},
            )

        remediation = db.scalars(
            select(RemediationRecommendation).where(
                RemediationRecommendation.incident_id == incident_id
            ).order_by(RemediationRecommendation.created_at.asc()).limit(1)
        ).first()
        if remediation is None:
            return
        repository.link_run_artifacts(db, chaos_run=run, remediation_id=remediation.id)
        self._record_once(
            db, run, ChaosObservationType.REMEDIATION_RECOMMENDED,
            remediation.created_at, "RemediationRecommendation",
            str(remediation.id), {"status": remediation.status.value},
        )
        approval = db.scalars(
            select(RemediationApproval).where(
                RemediationApproval.remediation_id == remediation.id
            ).limit(1)
        ).first()
        if approval is not None:
            self._record_once(
                db, run, ChaosObservationType.REMEDIATION_APPROVED,
                approval.approved_at, "RemediationApproval", str(approval.id),
                {"decision": approval.decision.value},
            )
        execution = db.scalars(
            select(RemediationExecution).where(
                RemediationExecution.remediation_id == remediation.id
            ).order_by(RemediationExecution.created_at.asc()).limit(1)
        ).first()
        if execution is not None:
            repository.link_run_artifacts(
                db, chaos_run=run, remediation_execution_id=execution.id
            )
            self._record_once(
                db, run, ChaosObservationType.REMEDIATION_EXECUTED,
                execution.completed_at or execution.created_at,
                "RemediationExecution", str(execution.id),
                {"status": execution.execution_status.value},
            )
            verification = execution.recovery_verification
            if verification is not None:
                repository.link_run_artifacts(
                    db, chaos_run=run, recovery_verification_id=verification.id
                )


def execute_run(
    *,
    db: Session,
    chaos_run_id: UUID,
    adapter: BaseChaosAdapter,
    observer: PlatformIQObserver | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> ChaosRun:
    """Execute one run and guarantee resource cleanup on every path."""
    from app.chaos.service import cleanup_chaos_run

    observer = observer or DatabasePlatformIQObserver()
    run = repository.get_run_by_id(db, chaos_run_id, for_update=True)
    if run is None:
        raise ChaosRunNotFoundError("Chaos run was not found")
    if run.status in {
        ChaosRunStatus.COMPLETED,
        ChaosRunStatus.FAILED,
        ChaosRunStatus.ABORTED,
    }:
        return run

    succeeded = False
    failure_message: str | None = None
    final_status = ChaosRunStatus.FAILED
    cleanup_resource: tuple[str, str] | None = None
    try:
        repository.update_run(db, chaos_run=run, status=ChaosRunStatus.RUNNING)
        db.commit()
        baseline = observer.capture_baseline(db, run)

        manifest = build_podchaos_manifest(
            run_id=str(run.id),
            environment=run.target_environment,
            namespace=run.target_namespace,
            service_name=run.experiment.target_service.name,
            operator_id=run.triggered_by or "system",
            deadline=_as_utc(run.deadline_at).isoformat(),
            duration_seconds=run.duration_seconds,
        )
        # The manifest identity is deterministic. Retain it before the API call
        # so cleanup remains possible even if persistence fails after creation.
        cleanup_resource = (
            str(manifest["kind"]),
            str(manifest["metadata"]["name"]),
        )
        resource = adapter.inject_fault(
            namespace=run.target_namespace,
            manifest=manifest,
        )
        injected_at = _injected_at(resource)
        repository.update_run(
            db,
            chaos_run=run,
            status=ChaosRunStatus.FAULT_INJECTED,
            failure_injected_at=injected_at,
            kubernetes_resource_kind=resource["resource_kind"],
            kubernetes_resource_name=resource["resource_name"],
            kubernetes_resource_uid=resource.get("resource_uid"),
        )
        repository.create_observation(
            db,
            chaos_run_id=run.id,
            observation_type=ChaosObservationType.FAILURE_INJECTED,
            source=CHAOS_OBSERVATION_SOURCE,
            observed_at=injected_at,
            resource_type=resource["resource_kind"],
            resource_id=resource["resource_name"],
            details=dict(resource),
        )
        repository.update_run(db, chaos_run=run, status=ChaosRunStatus.OBSERVING)
        db.commit()

        timeout = float(
            run.duration_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        stop_at = monotonic() + timeout
        while True:
            db.refresh(run)
            if run.status == ChaosRunStatus.ABORTED:
                failure_message = run.failure_message or "cancelled by operator"
                final_status = ChaosRunStatus.ABORTED
                break
            result = observer.observe(db, run, baseline)
            if getattr(result, "recovered", bool(result)):
                succeeded = True
                final_status = ChaosRunStatus.COMPLETED
                break
            remaining = stop_at - monotonic()
            if remaining <= 0:
                raise ChaosRunTimeoutError(
                    f"Recovery was not observed within {timeout:g} seconds"
                )
            sleeper(min(poll_interval_seconds, remaining))
    except Exception as exc:
        failure_message = str(exc)
        db.rollback()
    finally:
        run = repository.get_run_by_id(db, chaos_run_id, for_update=True)
        if run is None:
            raise ChaosRunNotFoundError("Chaos run was not found")
        if run.status == ChaosRunStatus.ABORTED:
            final_status = ChaosRunStatus.ABORTED
        if cleanup_resource and not run.kubernetes_resource_name:
            repository.update_run(
                db,
                chaos_run=run,
                kubernetes_resource_kind=cleanup_resource[0],
                kubernetes_resource_name=cleanup_resource[1],
            )
            db.commit()
        try:
            run = cleanup_chaos_run(
                db=db,
                chaos_run=run,
                adapter=adapter,
                reason=failure_message or "experiment completed",
                aborted=final_status == ChaosRunStatus.ABORTED,
                final_status=final_status,
            )
        except Exception as cleanup_exc:
            db.rollback()
            run = repository.get_run_by_id(db, chaos_run_id, for_update=True)
            if run is None:
                raise
            repository.update_run(
                db,
                chaos_run=run,
                status=ChaosRunStatus.FAILED,
                failure_message=failure_message or str(cleanup_exc),
                cleanup_succeeded=False,
                cleanup_error=str(cleanup_exc),
            )
            db.commit()
            succeeded = False
        try:
            calculate_benchmark(db, run, successful=succeeded)
        except Exception as benchmark_exc:
            db.rollback()
            run = repository.get_run_by_id(db, chaos_run_id, for_update=True)
            if run is None:
                raise
            repository.update_run(
                db,
                chaos_run=run,
                status=ChaosRunStatus.FAILED,
                failure_message=f"Benchmark calculation failed: {benchmark_exc}",
            )
            db.commit()
        db.refresh(run)
    return run