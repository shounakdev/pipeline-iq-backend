"""Approved remediation command execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    ActionType,
    RemediationExecution,
    RemediationRecommendation,
)
from app.remediation import repository
from app.remediation.adapters.mock_adapter import (
    MockRemediationAdapter,
)
from app.remediation.events import (
    create_remediation_execution_completed_event,
    create_remediation_execution_failed_event,
    create_remediation_execution_started_event,
)
from app.remediation.services.safety_service import (
    validate_execution_safety,
)


class RemediationExecutionError(Exception):
    """Raised when a remediation command fails."""


@dataclass(frozen=True)
class RemediationExecutionResult:
    recommendation: RemediationRecommendation
    execution: RemediationExecution
    output: dict[str, Any]


def _evidence_summary(
    recommendation: RemediationRecommendation,
) -> dict[str, Any]:
    if isinstance(
        recommendation.evidence_summary,
        dict,
    ):
        return recommendation.evidence_summary

    return {}


def _positive_integer(
    value: Any,
    *,
    default: int,
) -> int:
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return default

    return parsed_value if parsed_value > 0 else default


def _build_command_payload(
    recommendation: RemediationRecommendation,
) -> dict[str, Any]:
    evidence = _evidence_summary(recommendation)

    common_payload = {
        "recommendation_id": str(
            recommendation.id,
        ),
        "incident_id": str(
            recommendation.incident_id,
        ),
        "service_id": str(
            recommendation.service_id,
        ),
        "environment": recommendation.environment,
        "action_type": recommendation.action_type.value,
        "simulated": True,
    }

    if (
        recommendation.action_type
        == ActionType.ROLLBACK_DEPLOYMENT
    ):
        return {
            **common_payload,
            "command_type": "ARGOCD_ROLLBACK",
            "deployment_id": (
                evidence.get("deployment_id")
                or evidence.get(
                    "suspected_deployment_id"
                )
            ),
            "target_revision": (
                evidence.get(
                    "previous_healthy_revision"
                )
                or evidence.get(
                    "previous_revision"
                )
                or "previous_healthy_revision"
            ),
        }

    if (
        recommendation.action_type
        == ActionType.RESTART_POD
    ):
        return {
            **common_payload,
            "command_type": (
                "KUBERNETES_RESTART_POD"
            ),
            "target_pod": (
                evidence.get("pod_name")
                or evidence.get(
                    "unhealthy_pod_name"
                )
                or "unhealthy_pod"
            ),
        }

    if (
        recommendation.action_type
        == ActionType.SCALE_REPLICAS
    ):
        replica_count = _positive_integer(
            evidence.get("recommended_replicas")
            or evidence.get("target_replicas"),
            default=2,
        )

        return {
            **common_payload,
            "command_type": (
                "KUBERNETES_SCALE_REPLICAS"
            ),
            "replica_count": replica_count,
        }

    if (
        recommendation.action_type
        == ActionType.REDEPLOY_REVISION
    ):
        return {
            **common_payload,
            "command_type": (
                "ARGOCD_REDEPLOY_REVISION"
            ),
            "target_revision": (
                evidence.get("deployment_revision")
                or evidence.get("revision")
                or "current_revision"
            ),
        }

    raise RemediationExecutionError(
        "Unsupported remediation action"
    )


def execute_remediation(
    *,
    db: Session,
    remediation_id: UUID,
    adapter: MockRemediationAdapter | None = None,
    now: datetime | None = None,
) -> RemediationExecutionResult:
    safety_result = validate_execution_safety(
        db=db,
        remediation_id=remediation_id,
        now=now,
    )

    recommendation = safety_result.recommendation
    started_at = now or datetime.now(timezone.utc)
    command_payload = _build_command_payload(
        recommendation,
    )

    execution = repository.create_remediation_execution(
        db,
        remediation=recommendation,
        command_payload=command_payload,
        started_at=started_at,
    )

    create_remediation_execution_started_event(
        db=db,
        recommendation=recommendation,
        execution=execution,
    )

    selected_adapter = (
        adapter or MockRemediationAdapter()
    )

    try:
        output = selected_adapter.execute(
            action_type=recommendation.action_type,
            command_payload=command_payload,
        )
    except Exception as exc:
        completed_at = datetime.now(timezone.utc)

        repository.fail_remediation_execution(
            db,
            remediation=recommendation,
            execution=execution,
            error_message=str(exc),
            completed_at=completed_at,
        )

        create_remediation_execution_failed_event(
            db=db,
            recommendation=recommendation,
            execution=execution,
        )

        db.commit()

        raise RemediationExecutionError(
            "Remediation command execution failed"
        ) from exc

    completed_at = (
        started_at
        if now is not None
        else datetime.now(timezone.utc)
    )

    repository.complete_remediation_execution(
        db,
        remediation=recommendation,
        execution=execution,
        result_summary=output,
        completed_at=completed_at,
    )

    create_remediation_execution_completed_event(
        db=db,
        recommendation=recommendation,
        execution=execution,
    )

    db.commit()
    db.refresh(recommendation)
    db.refresh(execution)

    return RemediationExecutionResult(
        recommendation=recommendation,
        execution=execution,
        output=output,
    )