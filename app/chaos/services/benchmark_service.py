"""Calculate the outcome and timings for a completed chaos experiment."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.chaos import repository
from app.chaos.config import ChaosSettings
from app.models import (
    ApprovalDecision,
    BenchmarkStatus,
    ChaosObservation,
    ChaosObservationType,
    ChaosRun,
    DiagnosisRating,
    ExperimentBenchmark,
    RCAReportStatus,
    RecoveryVerificationStatus,
    RemediationExecutionStatus,
)


# RCA has used two category vocabularies over its lifetime.  Families let an
# expected category from either vocabulary receive a partial score when the
# report identifies the same area but not the exact category.
_CATEGORY_FAMILIES = (
    frozenset({"APPLICATION_REGRESSION", "APPLICATION_ERROR", "PIPELINE_QUALITY"}),
    frozenset({"RELEASE_CONFIGURATION", "DEPLOYMENT_CHANGE"}),
    frozenset({"DATABASE_DEPENDENCY", "DEPENDENCY_FAILURE", "EXTERNAL_DEPENDENCY"}),
    frozenset({"NETWORK_DEPENDENCY", "DEPENDENCY_FAILURE"}),
    frozenset({"RESOURCE_EXHAUSTION", "CAPACITY_OR_SCALING", "INFRASTRUCTURE"}),
    frozenset({"KUBERNETES_RUNTIME", "KUBERNETES", "INFRASTRUCTURE"}),
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _duration_ms(
    start: datetime | None,
    end: datetime | None,
    *,
    metric: str,
) -> int | None:
    if start is None or end is None:
        return None
    milliseconds = int((_as_utc(end) - _as_utc(start)).total_seconds() * 1000)
    if milliseconds < 0:
        raise ValueError(f"{metric} cannot be negative")
    return milliseconds


def _value(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    normalized = str(raw).strip().upper().replace("-", "_").replace(" ", "_")
    return normalized or None


def rate_diagnosis(
    expected_root_cause: Any,
    actual_root_cause: Any,
    *,
    rca_completed: bool,
) -> DiagnosisRating:
    """Grade the completed RCA category against the experiment expectation."""
    if not rca_completed:
        return DiagnosisRating.NOT_AVAILABLE

    expected = _value(expected_root_cause)
    actual = _value(actual_root_cause)
    if expected is None or actual is None:
        return DiagnosisRating.INCORRECT
    if expected == actual:
        return DiagnosisRating.CORRECT
    if any(expected in family and actual in family for family in _CATEGORY_FAMILIES):
        return DiagnosisRating.PARTIALLY_CORRECT
    return DiagnosisRating.INCORRECT


def _expected_root_cause(run: ChaosRun) -> Any:
    experiment = run.experiment
    explicit = getattr(experiment, "expected_root_cause", None)
    if explicit is not None:
        return explicit
    behavior = (
        experiment.expected_behavior
        if isinstance(experiment.expected_behavior, dict)
        else {}
    )
    return behavior.get("expected_root_cause", behavior.get("root_cause"))


def _actual_root_cause(run: ChaosRun) -> tuple[Any, bool]:
    report = run.rca_report
    completed = bool(
        report is not None
        and report.status == RCAReportStatus.COMPLETED
        and report.generated_at is not None
    )
    if not completed:
        return None, False
    explicit = getattr(report, "root_cause_category", None)
    if explicit is not None:
        return explicit, True
    payload = report.report_json if isinstance(report.report_json, dict) else {}
    return payload.get("root_cause_category"), True


def _first_observations(
    observations: list[ChaosObservation],
) -> dict[ChaosObservationType, ChaosObservation]:
    first: dict[ChaosObservationType, ChaosObservation] = {}
    for observation in sorted(observations, key=lambda item: _as_utc(item.observed_at)):
        first.setdefault(observation.observation_type, observation)
    return first


def _recovery_succeeded(run: ChaosRun, recovery: ChaosObservation | None) -> bool:
    verification = run.recovery_verification
    if verification is not None:
        return verification.verification_status == RecoveryVerificationStatus.VERIFIED
    details = (
        recovery.details
        if recovery is not None and isinstance(recovery.details, dict)
        else {}
    )
    return details.get("recovery_succeeded") is True


def _remediation_completed(run: ChaosRun, executed: ChaosObservation | None) -> bool:
    execution = run.remediation_execution
    if execution is not None:
        return execution.execution_status == RemediationExecutionStatus.SUCCEEDED
    if executed is None:
        return False
    details = executed.details if isinstance(executed.details, dict) else {}
    return _value(details.get("status")) == RemediationExecutionStatus.SUCCEEDED.value


def _approval_succeeded(run: ChaosRun, approved: ChaosObservation | None) -> bool:
    approval = run.remediation.approval if run.remediation is not None else None
    if approval is not None:
        return approval.decision == ApprovalDecision.APPROVED
    if approved is None:
        return False
    details = approved.details if isinstance(approved.details, dict) else {}
    return _value(details.get("decision")) == ApprovalDecision.APPROVED.value


def calculate_benchmark(
    db: Session,
    run: ChaosRun,
    *,
    settings: ChaosSettings | None = None,
    calculated_at: datetime | None = None,
    successful: bool | None = None,
) -> ExperimentBenchmark:
    """Calculate and persist one deterministic benchmark for ``run``.

    ``successful`` is retained for compatibility with the run orchestrator;
    benchmark status is derived from the measured evidence, not that flag.
    """
    del successful
    settings = settings or ChaosSettings.from_env()
    observations = repository.list_observations_for_run(db, run.id)
    first = _first_observations(observations)

    injected = run.failure_injected_at or getattr(
        first.get(ChaosObservationType.FAILURE_INJECTED), "observed_at", None
    )
    anomaly_observation = first.get(ChaosObservationType.TELEMETRY_ANOMALY)
    alert_observation = first.get(ChaosObservationType.ALERT_CREATED)
    incident_observation = first.get(ChaosObservationType.INCIDENT_CREATED)
    rca_observation = first.get(ChaosObservationType.RCA_COMPLETED)
    recommended_observation = first.get(ChaosObservationType.REMEDIATION_RECOMMENDED)
    approved_observation = first.get(ChaosObservationType.REMEDIATION_APPROVED)
    executed_observation = first.get(ChaosObservationType.REMEDIATION_EXECUTED)
    recovery_observation = first.get(ChaosObservationType.RECOVERY_COMPLETED)

    def timestamp(observation: ChaosObservation | None) -> datetime | None:
        return observation.observed_at if observation is not None else None

    anomaly = timestamp(anomaly_observation)
    alert = timestamp(alert_observation)
    incident = timestamp(incident_observation)
    rca = timestamp(rca_observation)
    recommended = timestamp(recommended_observation)
    approved = timestamp(approved_observation)
    recovery = timestamp(recovery_observation)

    durations = {
        "time_to_detect_ms": _duration_ms(injected, anomaly, metric="time to detect"),
        "time_to_alert_ms": _duration_ms(injected, alert, metric="time to alert"),
        "time_to_incident_ms": _duration_ms(
            injected,
            incident,
            metric="time to incident",
        ),
        "time_to_diagnose_ms": _duration_ms(incident, rca, metric="time to diagnose"),
        "time_to_approve_ms": _duration_ms(
            recommended,
            approved,
            metric="approval delay",
        ),
        "time_to_recover_ms": _duration_ms(
            injected,
            recovery,
            metric="time to recover",
        ),
    }

    expected = _expected_root_cause(run)
    actual, rca_completed = _actual_root_cause(run)
    diagnosis = rate_diagnosis(expected, actual, rca_completed=rca_completed)
    recovery_succeeded = _recovery_succeeded(run, recovery_observation)
    remediation_completed = _remediation_completed(run, executed_observation)
    approval_succeeded = _approval_succeeded(run, approved_observation)

    required_timestamps = (
        injected,
        anomaly,
        alert,
        incident,
        rca,
        recommended,
        approved,
        timestamp(executed_observation),
        recovery,
    )
    if any(value is None for value in required_timestamps) or not rca_completed:
        status = BenchmarkStatus.INCOMPLETE
    else:
        acceptable_diagnosis = diagnosis in {
            DiagnosisRating.CORRECT,
            DiagnosisRating.PARTIALLY_CORRECT,
        }
        within_thresholds = (
            durations["time_to_detect_ms"] <= settings.max_detection_seconds * 1000
            and durations["time_to_alert_ms"] <= settings.max_alert_seconds * 1000
            and durations["time_to_incident_ms"] <= settings.max_incident_seconds * 1000
            and durations["time_to_diagnose_ms"]
            <= settings.max_diagnosis_seconds * 1000
            and durations["time_to_recover_ms"] <= settings.max_recovery_seconds * 1000
        )
        status = (
            BenchmarkStatus.PASSED
            if acceptable_diagnosis
            and approval_succeeded
            and remediation_completed
            and recovery_succeeded
            and within_thresholds
            else BenchmarkStatus.FAILED
        )

    benchmark = repository.save_benchmark(
        db,
        chaos_run_id=run.id,
        values={
            "failure_injection_timestamp": injected,
            "first_anomaly_timestamp": anomaly,
            "alert_creation_timestamp": alert,
            "incident_creation_timestamp": incident,
            "rca_completion_timestamp": rca,
            "remediation_approval_timestamp": approved,
            "recovery_completion_timestamp": recovery,
            **durations,
            "diagnosis_rating": diagnosis,
            "expected_root_cause": _value(expected),
            "actual_root_cause": _value(actual),
            "detection_succeeded": anomaly is not None,
            "recovery_succeeded": recovery_succeeded,
            "benchmark_status": status,
            "calculated_at": calculated_at or datetime.now(timezone.utc),
        },
    )
    db.commit()
    return benchmark


__all__ = ["calculate_benchmark", "rate_diagnosis"]