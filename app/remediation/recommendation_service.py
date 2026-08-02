from __future__ import annotations

from app.remediation.events import (
    create_remediation_recommended_event,
)

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    ActionType,
    RCAConfidence,
)
from app.remediation import repository
from app.remediation.schemas import RemediationRecommendationCreate


DEFAULT_CORRELATION_WINDOW_MINUTES = 60

FAILED_ROLLOUT_STATUSES = {
    "FAILED",
    "INCOMPLETE",
    "PROGRESS_DEADLINE_EXCEEDED",
}

DEPLOYMENT_LINKED_CATEGORIES = {
    "DEPLOYMENT_CHANGE",
    "RELEASE_REGRESSION",
}

APPLICATION_REGRESSION_CATEGORIES = {
    "APPLICATION_REGRESSION",
    "APPLICATION_ERROR",
    "RELEASE_REGRESSION",
}

REGRESSION_FACTS = {
    "APPLICATION_REGRESSION",
    "RELEASE_REGRESSION",
    "ERROR_RATE_INCREASED_AFTER_DEPLOYMENT",
    "LATENCY_INCREASED_AFTER_DEPLOYMENT",
}

TEMPORAL_DEPLOYMENT_FACTS = {
    "DEPLOYMENT_TEMPORAL_CORRELATION",
    "DEPLOYMENT_SHORTLY_BEFORE_FAILURE",
}

RESOURCE_SATURATION_FACTS = {
    "RESOURCE_SATURATION",
    "CPU_SATURATION",
    "MEMORY_SATURATION",
}

RESTARTABLE_POD_STATES = {
    "CRASHLOOPBACKOFF",
    "NOTREADY",
    "UNKNOWN",
    "STUCKTERMINATING",
}


class RemediationRecommendationError(Exception):
    pass


class IncidentNotFoundError(RemediationRecommendationError):
    pass

class IncidentEvidenceMissingError(
    RemediationRecommendationError,
):
    pass


class RCAReportMissingError(
    RemediationRecommendationError,
):
    pass


class NoSafeRemediationError(
    RemediationRecommendationError,
):
    pass


class RecommendationInputsNotChangedError(
    RemediationRecommendationError,
):
    pass


@dataclass(frozen=True)
class RecommendationServiceResult:
    recommendation: Any
    created: bool


@dataclass(frozen=True)
class RecommendationDecision:
    action_type: ActionType | None
    reason: str
    confidence: RCAConfidence | None
    evidence_summary: dict[str, Any]
    rule_code: str | None


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _normalise_text(value: Any) -> str:
    if value is None:
        return ""

    return (
        str(_enum_value(value))
        .strip()
        .upper()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _normalise_pod_state(value: Any) -> str:
    return _normalise_text(value).replace("_", "")


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)

    if number is None or not number.is_integer():
        return None

    return int(number)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00"),
            )
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed


def _first_present(
    sources: list[dict[str, Any]],
    *keys: str,
) -> Any:
    for source in sources:
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]

    return None


def _fact_types(evidence_payload: dict[str, Any]) -> set[str]:
    facts = []

    facts.extend(
        _list_value(
            evidence_payload.get("derived_facts"),
        )
    )
    facts.extend(
        _list_value(
            evidence_payload.get("correlation_facts"),
        )
    )

    result = set()

    for fact in facts:
        if not isinstance(fact, dict):
            continue

        polarity = _normalise_text(
            fact.get("polarity", "SUPPORTING"),
        )

        if polarity == "CONTRADICTORY":
            continue

        fact_type = _normalise_text(
            fact.get("fact_type") or fact.get("fact"),
        )

        if fact_type:
            result.add(fact_type)

    return result


def _report_category(report: Any) -> str:
    if report is None:
        return ""

    report_payload = _dict_value(
        getattr(report, "report_json", None),
    )

    return _normalise_text(
        report_payload.get("root_cause_category"),
    )


def _decision_confidence(report: Any) -> RCAConfidence:
    if report is not None:
        value = (
            _enum_value(getattr(report, "confidence", None))
            or _dict_value(
                getattr(report, "report_json", None),
            ).get("confidence")
        )

        try:
            return RCAConfidence(
                _normalise_text(value),
            )
        except ValueError:
            pass

    return RCAConfidence.MEDIUM


def _rollout_failed(
    *,
    deployment_payload: dict[str, Any],
    kubernetes: dict[str, Any],
    deployment: Any,
) -> tuple[bool, dict[str, Any]]:
    rollout_status = _normalise_text(
        _first_present(
            [kubernetes, deployment_payload],
            "rollout_status",
            "deployment_status",
            "kubernetes_rollout_status",
        )
        or getattr(
            deployment,
            "kubernetes_rollout_status",
            None,
        )
    )

    if rollout_status in FAILED_ROLLOUT_STATUSES:
        return True, {
            "rollout_status": rollout_status,
        }

    desired_replicas = _integer(
        _first_present(
            [kubernetes, deployment_payload],
            "desired_replicas",
        )
    )
    available_replicas = _integer(
        _first_present(
            [kubernetes, deployment_payload],
            "available_replicas",
            "available_replicas_after",
        )
    )
    rollout_completed = _first_present(
        [kubernetes, deployment_payload],
        "rollout_completed",
    )

    incomplete = (
        desired_replicas is not None
        and available_replicas is not None
        and desired_replicas > available_replicas
        and rollout_completed is False
    )

    return incomplete, {
        "rollout_status": rollout_status or None,
        "desired_replicas": desired_replicas,
        "available_replicas": available_replicas,
        "rollout_completed": rollout_completed,
    }


def _deployment_within_window(
    *,
    incident: Any,
    deployment_payload: dict[str, Any],
    deployment: Any,
    correlation_window_minutes: int,
) -> tuple[bool, float | None]:
    minutes_before_failure = _number(
        deployment_payload.get(
            "minutes_before_failure",
        )
    )

    if minutes_before_failure is not None:
        return (
            0
            <= minutes_before_failure
            <= correlation_window_minutes,
            minutes_before_failure,
        )

    deployed_at = _parse_datetime(
        deployment_payload.get("deployed_at")
        or getattr(deployment, "deployed_at", None)
    )
    failure_time = _parse_datetime(
        getattr(incident, "failure_started_at", None)
        or getattr(incident, "detected_at", None)
    )

    if not deployed_at or not failure_time:
        return False, None

    minutes = (
        failure_time - deployed_at
    ).total_seconds() / 60

    return (
        0 <= minutes <= correlation_window_minutes,
        minutes,
    )


def _health_regressed(
    *,
    metrics: dict[str, Any],
    facts: set[str],
) -> bool:
    error_before = _number(
        metrics.get("error_rate_before"),
    )
    error_after = _number(
        metrics.get("error_rate_after"),
    )
    latency_before = _number(
        metrics.get("p95_latency_before_ms")
        or metrics.get("p95_latency_before"),
    )
    latency_after = _number(
        metrics.get("p95_latency_after_ms")
        or metrics.get("p95_latency_after"),
    )

    error_regressed = (
        error_before is not None
        and error_after is not None
        and error_after > error_before
    )
    latency_regressed = (
        latency_before is not None
        and latency_after is not None
        and latency_after > latency_before
    )

    return (
        error_regressed
        or latency_regressed
        or bool(facts & REGRESSION_FACTS)
    )


def _rollback_supported(
    *,
    incident: Any,
    deployment_payload: dict[str, Any],
    metrics: dict[str, Any],
    deployment: Any,
    report_category: str,
    facts: set[str],
    correlation_window_minutes: int,
) -> tuple[bool, dict[str, Any]]:
    if deployment is None:
        return False, {}

    within_window, minutes = _deployment_within_window(
        incident=incident,
        deployment_payload=deployment_payload,
        deployment=deployment,
        correlation_window_minutes=correlation_window_minutes,
    )

    if not within_window:
        return False, {}

    regression = _health_regressed(
        metrics=metrics,
        facts=facts,
    )

    temporal_link = bool(
        facts & TEMPORAL_DEPLOYMENT_FACTS
    )

    rca_links_deployment = (
        report_category
        in DEPLOYMENT_LINKED_CATEGORIES
        or (
            report_category
            in APPLICATION_REGRESSION_CATEGORIES
            and temporal_link
        )
    )

    derived_facts_link_deployment = bool(
        facts & REGRESSION_FACTS
    )

    previous_revision = (
        getattr(deployment, "previous_revision", None)
        or deployment_payload.get(
            "previous_stable_revision",
        )
        or deployment_payload.get(
            "previous_revision",
        )
    )

    supported = (
        regression
        and (
            rca_links_deployment
            or derived_facts_link_deployment
        )
        and bool(previous_revision)
    )

    return supported, {
        "deployment_id": str(
            getattr(deployment, "id", ""),
        ),
        "minutes_before_failure": minutes,
        "root_cause_category": (
            report_category or None
        ),
        "previous_revision": previous_revision,
        "regression_facts": sorted(
            facts & REGRESSION_FACTS,
        ),
        "temporal_facts": sorted(
            facts & TEMPORAL_DEPLOYMENT_FACTS,
        ),
    }


def _pod_is_restartable(
    pod: dict[str, Any],
) -> bool:
    state = _normalise_pod_state(
        pod.get("state")
        or pod.get("status")
        or pod.get("reason")
    )

    if state in RESTARTABLE_POD_STATES:
        return True

    if (
        pod.get("deletion_timestamp")
        and state in {"TERMINATING", "UNKNOWN"}
    ):
        return True

    readiness_failures = _integer(
        pod.get("readiness_failure_count")
        or pod.get("failed_readiness_probe_count")
    )

    return (
        readiness_failures is not None
        and readiness_failures >= 2
    )


def _single_unhealthy_pod(
    kubernetes: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    pod_statuses = _list_value(
        kubernetes.get("pod_statuses")
        or kubernetes.get("pods")
    )

    unhealthy_pods = [
        pod
        for pod in pod_statuses
        if isinstance(pod, dict)
        and _pod_is_restartable(pod)
    ]

    if pod_statuses:
        if len(unhealthy_pods) != 1:
            return False, {}

        pod = unhealthy_pods[0]

        return True, {
            "unhealthy_pod_count": 1,
            "pod_name": (
                pod.get("name")
                or pod.get("pod_name")
            ),
            "pod_state": (
                pod.get("state")
                or pod.get("status")
                or pod.get("reason")
            ),
        }

    unhealthy_count = _integer(
        kubernetes.get("unhealthy_pod_count"),
    )

    if unhealthy_count != 1:
        return False, {}

    crash_loop_count = _integer(
        kubernetes.get("crash_loop_count"),
    )
    readiness_failures = _integer(
        kubernetes.get(
            "failed_readiness_probe_count",
        )
    )
    unhealthy_state = _normalise_pod_state(
        kubernetes.get("unhealthy_pod_state")
        or kubernetes.get("unhealthy_pod_reason")
    )

    recognised_state = (
        unhealthy_state in RESTARTABLE_POD_STATES
        or crash_loop_count == 1
        or (
            readiness_failures is not None
            and readiness_failures >= 2
        )
    )

    if not recognised_state:
        return False, {}

    return True, {
        "unhealthy_pod_count": 1,
        "pod_name": kubernetes.get(
            "unhealthy_pod_name",
        ),
        "pod_state": (
            unhealthy_state or None
        ),
        "crash_loop_count": crash_loop_count,
        "failed_readiness_probe_count": (
            readiness_failures
        ),
    }


def _sustained_resource_pressure(
    *,
    metrics: dict[str, Any],
    kubernetes: dict[str, Any],
    health_history: list[Any],
    report_category: str,
    facts: set[str],
) -> tuple[bool, dict[str, Any]]:
    cpu_saturated = (
        metrics.get("cpu_saturated") is True
        or kubernetes.get("cpu_saturated") is True
        or _normalise_text(
            kubernetes.get("cpu_status"),
        )
        in {"HIGH", "SATURATED"}
    )
    memory_saturated = (
        metrics.get("memory_saturated") is True
        or kubernetes.get("memory_saturated") is True
        or _normalise_text(
            kubernetes.get("memory_status"),
        )
        in {"HIGH", "SATURATED"}
    )

    structured_saturation = (
        report_category == "RESOURCE_SATURATION"
        or bool(
            facts & RESOURCE_SATURATION_FACTS,
        )
    )

    recent_samples = health_history[:3]

    sustained_cpu_samples = (
        len(recent_samples) == 3
        and all(
            _number(snapshot.cpu_usage) is not None
            and _number(snapshot.cpu_usage) >= 85
            for snapshot in recent_samples
        )
    )
    sustained_memory_samples = (
        len(recent_samples) == 3
        and all(
            _number(snapshot.memory_usage) is not None
            and _number(snapshot.memory_usage) >= 85
            for snapshot in recent_samples
        )
    )

    sustained_flag = (
        metrics.get("saturation_sustained") is True
        or metrics.get("cpu_saturation_sustained")
        is True
        or metrics.get(
            "memory_saturation_sustained",
        )
        is True
    )

    resource_pressure = (
        cpu_saturated
        or memory_saturated
        or structured_saturation
        or sustained_cpu_samples
        or sustained_memory_samples
    )
    sustained = (
        sustained_flag
        or structured_saturation
        or sustained_cpu_samples
        or sustained_memory_samples
    )

    return resource_pressure and sustained, {
        "cpu_saturated": cpu_saturated,
        "memory_saturated": memory_saturated,
        "structured_saturation": (
            structured_saturation
        ),
        "sustained_cpu_samples": (
            sustained_cpu_samples
        ),
        "sustained_memory_samples": (
            sustained_memory_samples
        ),
    }


def _scale_supported(
    *,
    metrics: dict[str, Any],
    kubernetes: dict[str, Any],
    latest_health: Any,
    health_history: list[Any],
    report_category: str,
    facts: set[str],
) -> tuple[bool, dict[str, Any]]:
    saturation_verified, saturation_evidence = (
        _sustained_resource_pressure(
            metrics=metrics,
            kubernetes=kubernetes,
            health_history=health_history,
            report_category=report_category,
            facts=facts,
        )
    )

    request_before = _number(
        metrics.get("request_rate_before"),
    )
    request_after = _number(
        metrics.get("request_rate_after"),
    )

    request_load_elevated = (
        metrics.get("request_load_elevated") is True
        or (
            request_before is not None
            and request_after is not None
            and request_after
            > request_before * 1.2
        )
    )

    desired_replicas = _integer(
        kubernetes.get("desired_replicas")
    )
    available_replicas = _integer(
        _first_present(
            [kubernetes],
            "available_replicas",
            "available_replicas_after",
        )
    )

    if latest_health is not None:
        if desired_replicas is None:
            desired_replicas = _integer(
                latest_health.replica_count,
            )

        if available_replicas is None:
            available_replicas = _integer(
                latest_health.available_replicas,
            )

    maximum_replicas = _integer(
        _first_present(
            [kubernetes],
            "maximum_replicas",
            "max_replicas",
        )
    )

    maximum_not_reached = (
        kubernetes.get(
            "maximum_replica_limit_not_reached",
        )
        is True
        or (
            maximum_replicas is not None
            and desired_replicas is not None
            and desired_replicas
            < maximum_replicas
        )
    )

    replicas_fully_available = (
        desired_replicas is not None
        and available_replicas is not None
        and desired_replicas
        == available_replicas
    )

    supported = (
        saturation_verified
        and request_load_elevated
        and replicas_fully_available
        and maximum_not_reached
    )

    return supported, {
        **saturation_evidence,
        "request_load_elevated": (
            request_load_elevated
        ),
        "request_rate_before": request_before,
        "request_rate_after": request_after,
        "desired_replicas": desired_replicas,
        "available_replicas": (
            available_replicas
        ),
        "maximum_replicas": maximum_replicas,
        "maximum_replica_limit_not_reached": (
            maximum_not_reached
        ),
    }


def evaluate_remediation_recommendation(
    *,
    incident: Any,
    evidence_payload: dict[str, Any],
    report: Any = None,
    deployment: Any = None,
    latest_health: Any = None,
    health_history: list[Any] | None = None,
    correlation_window_minutes: int = (
        DEFAULT_CORRELATION_WINDOW_MINUTES
    ),
) -> RecommendationDecision | None:
    if correlation_window_minutes <= 0:
        raise ValueError(
            "Correlation window must be greater than zero"
        )

    deployment_payload = _dict_value(
        evidence_payload.get("deployment"),
    )
    metrics = _dict_value(
        evidence_payload.get("metrics"),
    )
    kubernetes = _dict_value(
        evidence_payload.get("kubernetes"),
    )

    facts = _fact_types(evidence_payload)
    report_category = _report_category(report)
    confidence = _decision_confidence(report)

    rollout_failed, rollout_evidence = (
        _rollout_failed(
            deployment_payload=deployment_payload,
            kubernetes=kubernetes,
            deployment=deployment,
        )
    )

    if rollout_failed:
        rule_code = "FAILED_OR_INCOMPLETE_ROLLOUT"

        return RecommendationDecision(
            action_type=(
                ActionType.REDEPLOY_REVISION
            ),
            reason=(
                "The latest rollout failed or "
                "did not complete."
            ),
            confidence=RCAConfidence.HIGH,
            rule_code=rule_code,
            evidence_summary={
                "rule_code": rule_code,
                **rollout_evidence,
            },
        )

    rollback_supported, rollback_evidence = (
        _rollback_supported(
            incident=incident,
            deployment_payload=deployment_payload,
            metrics=metrics,
            deployment=deployment,
            report_category=report_category,
            facts=facts,
            correlation_window_minutes=(
                correlation_window_minutes
            ),
        )
    )

    if rollback_supported:
        rule_code = "RECENT_DEPLOYMENT_REGRESSION"

        return RecommendationDecision(
            action_type=(
                ActionType.ROLLBACK_DEPLOYMENT
            ),
            reason=(
                "Service reliability regressed "
                "shortly after the latest deployment."
            ),
            confidence=RCAConfidence.HIGH,
            rule_code=rule_code,
            evidence_summary={
                "rule_code": rule_code,
                **rollback_evidence,
            },
        )

    application_wide_regression = (
        report_category
        in APPLICATION_REGRESSION_CATEGORIES
        or bool(facts & REGRESSION_FACTS)
    )

    desired_replicas = _integer(
        kubernetes.get("desired_replicas"),
    )
    available_replicas = _integer(
        _first_present(
            [kubernetes],
            "available_replicas",
            "available_replicas_after",
        )
    )

    entire_workload_unavailable = (
        desired_replicas is not None
        and desired_replicas > 0
        and available_replicas == 0
    )

    one_unhealthy_pod, pod_evidence = (
        _single_unhealthy_pod(kubernetes)
    )

    if (
        one_unhealthy_pod
        and not application_wide_regression
        and not entire_workload_unavailable
    ):
        rule_code = "SINGLE_UNHEALTHY_POD"

        return RecommendationDecision(
            action_type=ActionType.RESTART_POD,
            reason=(
                "Exactly one pod is unhealthy "
                "or stuck."
            ),
            confidence=RCAConfidence.MEDIUM,
            rule_code=rule_code,
            evidence_summary={
                "rule_code": rule_code,
                **pod_evidence,
            },
        )

    scale_supported, scale_evidence = (
        _scale_supported(
            metrics=metrics,
            kubernetes=kubernetes,
            latest_health=latest_health,
            health_history=health_history or [],
            report_category=report_category,
            facts=facts,
        )
    )

    if scale_supported:
        rule_code = "VERIFIED_LOAD_SATURATION"

        return RecommendationDecision(
            action_type=ActionType.SCALE_REPLICAS,
            reason=(
                "Sustained workload saturation "
                "has been verified."
            ),
            confidence=RCAConfidence.HIGH,
            rule_code=rule_code,
            evidence_summary={
                "rule_code": rule_code,
                **scale_evidence,
            },
        )

    return RecommendationDecision(
        action_type=None,
        reason=(
            "Available evidence does not support "
            "a safe remediation."
        ),
        confidence=None,
        rule_code=None,
        evidence_summary={},
    )


def _deployment_id(
    incident: Any,
    evidence_payload: dict[str, Any],
) -> UUID | None:
    raw_id = (
        getattr(
            incident,
            "suspected_deployment_id",
            None,
        )
        or _dict_value(
            evidence_payload.get("deployment"),
        ).get("deployment_id")
    )

    if not raw_id:
        return None

    try:
        return UUID(str(raw_id))
    except (TypeError, ValueError):
        return None


def recommend_remediation(
    *,
    db: Session,
    incident_id: UUID,
    created_by: str | None = None,
    correlation_window_minutes: int = (
        DEFAULT_CORRELATION_WINDOW_MINUTES
    ),
) -> RecommendationServiceResult:
    incident = repository.get_incident_by_id(
        db,
        incident_id,
        for_update=True,
    )

    if incident is None:
        raise IncidentNotFoundError(
            "Incident not found"
        )

    if not incident.primary_service_id:
        raise NoSafeRemediationError(
            "The incident has no associated service."
        )

    evidence = (
        repository.get_latest_incident_evidence(
            db,
            incident_id,
        )
    )

    if evidence is None:
        raise IncidentEvidenceMissingError(
            "Incident evidence is missing."
        )

    evidence_status = _normalise_text(
        evidence.status,
    )

    if evidence_status not in {
        "COMPLETED",
        "PARTIAL",
    }:
        raise IncidentEvidenceMissingError(
            "Incident evidence is not ready."
        )

    evidence_payload = _dict_value(
        evidence.evidence_payload,
    )

    if not evidence_payload:
        raise IncidentEvidenceMissingError(
            "Incident evidence payload is empty."
        )

    report = repository.get_latest_rca_report(
        db,
        incident_id,
    )

    if report is None:
        raise RCAReportMissingError(
            "RCA report is missing."
        )

    report_status = _normalise_text(
        report.status,
    )

    if report_status != "COMPLETED":
        raise RCAReportMissingError(
            "RCA report is not ready."
        )

    deployment = None
    deployment_id = _deployment_id(
        incident,
        evidence_payload,
    )

    if deployment_id:
        deployment = (
            repository.get_deployment_by_id(
                db,
                deployment_id,
            )
        )

    latest_health = (
        repository.get_latest_service_health(
            db,
            service_id=(
                incident.primary_service_id
            ),
            environment=incident.environment,
        )
    )
    health_history = (
        repository.get_service_health_history(
            db,
            service_id=(
                incident.primary_service_id
            ),
            environment=incident.environment,
            limit=5,
        )
    )

    decision = (
        evaluate_remediation_recommendation(
            incident=incident,
            evidence_payload=evidence_payload,
            report=report,
            deployment=deployment,
            latest_health=latest_health,
            health_history=health_history,
            correlation_window_minutes=(
                correlation_window_minutes
            ),
        )
    )

    if decision.action_type is None:
        raise NoSafeRemediationError(
            decision.reason
        )

    active_recommendation = (
        repository.get_active_recommendation(
            db,
            incident_id=incident.id,
            action_type=decision.action_type,
        )
    )

    if active_recommendation is not None:
        return RecommendationServiceResult(
            recommendation=active_recommendation,
            created=False,
        )

    latest_recommendation = (
        repository.get_latest_recommendation(
            db,
            incident.id,
        )
    )

    if (
        latest_recommendation is not None
        and repository.recommendation_uses_source_snapshot(
            latest_recommendation,
            evidence_id=evidence.id,
            rca_report_id=report.id,
        )
    ):
        raise RecommendationInputsNotChangedError(
            "A newer RCA report or incident evidence "
            "record is required before reevaluation."
        )

    deployment_payload = _dict_value(
        evidence_payload.get("deployment"),
    )
    metrics = _dict_value(
        evidence_payload.get("metrics"),
    )
    matched_facts = sorted(
        _fact_types(evidence_payload),
    )

    deployment_revision = (
        _first_present(
            [deployment_payload],
            "deployment_revision",
            "version",
            "image_tag",
        )
        or getattr(
            deployment,
            "deployment_version",
            None,
        )
        or getattr(
            deployment,
            "image_tag",
            None,
        )
    )

    stored_deployment_id = (
        decision.evidence_summary.get(
            "deployment_id",
        )
        or deployment_payload.get(
            "deployment_id",
        )
        or (
            str(deployment.id)
            if deployment is not None
            else None
        )
    )

    deployed_minutes = (
        decision.evidence_summary.get(
            "minutes_before_failure",
        )
        or deployment_payload.get(
            "minutes_before_failure",
        )
    )

    health_before = {
        "error_rate": metrics.get(
            "error_rate_before",
        ),
        "latency_ms": _first_present(
            [metrics],
            "p95_latency_before_ms",
            "p95_latency_before",
        ),
    }
    health_after = {
        "error_rate": metrics.get(
            "error_rate_after",
        ),
        "latency_ms": _first_present(
            [metrics],
            "p95_latency_after_ms",
            "p95_latency_after",
        ),
    }

    evidence_summary = {
        **decision.evidence_summary,
        "rule_code": decision.rule_code,
        "incident_id": str(incident.id),
        "rca_report_id": str(report.id),
        "incident_evidence_id": str(
            evidence.id,
        ),
        "deployment_id": stored_deployment_id,
        "deployment_revision": (
            deployment_revision
        ),
        "deployed_minutes_before_incident": (
            deployed_minutes
        ),
        "health_before": health_before,
        "health_after": health_after,
        "matched_facts": matched_facts,
    }

    recommendation_data = (
        RemediationRecommendationCreate(
            incident_id=incident.id,
            service_id=(
                incident.primary_service_id
            ),
            environment=incident.environment,
            action_type=decision.action_type,
            reason=decision.reason,
            evidence_summary=evidence_summary,
            confidence=decision.confidence,
            created_by=created_by,
        )
    )

    try:
        recommendation = (
            repository.create_recommendation(
                db,
                recommendation_data,
            )
        )

        repository.create_recommendation_audit_event(
            db,
            recommendation=recommendation,
            requested_by=created_by,
        )

        create_remediation_recommended_event(
            db=db,
            recommendation=recommendation,
        )

        db.commit()
        db.refresh(recommendation)

        return RecommendationServiceResult(
            recommendation=recommendation,
            created=True,
        )
    except Exception:
        db.rollback()
        raise