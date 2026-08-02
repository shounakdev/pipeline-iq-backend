from datetime import datetime, timezone

import pytest

from app.events.constants import (
    REMEDIATION_COMMAND_CREATED,
    REMEDIATION_COMPLETED,
    ROLLBACK_COMPLETED,
    ROLLBACK_STARTED,
    TOPIC_REMEDIATION_COMMANDS,
    TOPIC_REMEDIATION_RESULTS,
)
from app.models import (
    ActionType,
    OutboxEvent,
    RecommendationStatus,
    RemediationExecutionStatus,
)
from app.remediation.services.execution_service import (
    execute_remediation,
)
from app.remediation.services.safety_service import (
    DuplicateRemediationExecutionError,
)
from tests.remediation.test_safety_service import (
    create_decided_recommendation,
    create_service_context,
)


@pytest.mark.parametrize(
    (
        "action_type",
        "evidence_summary",
        "expected_command_type",
        "result_field",
        "expected_value",
    ),
    [
        (
            ActionType.ROLLBACK_DEPLOYMENT,
            {
                "deployment_revision": "v2.0.0",
                "previous_revision": "v1.9.0",
            },
            "ARGOCD_ROLLBACK",
            "target_revision",
            "v1.9.0",
        ),
        (
            ActionType.RESTART_POD,
            {
                "pod_name": "payment-api-7d9f",
            },
            "KUBERNETES_RESTART_POD",
            "target_pod",
            "payment-api-7d9f",
        ),
        (
            ActionType.SCALE_REPLICAS,
            {
                "recommended_replicas": 5,
            },
            "KUBERNETES_SCALE_REPLICAS",
            "replica_count",
            5,
        ),
        (
            ActionType.REDEPLOY_REVISION,
            {
                "deployment_revision": "v2.1.0",
            },
            "ARGOCD_REDEPLOY_REVISION",
            "target_revision",
            "v2.1.0",
        ),
    ],
)
def test_executes_supported_remediation_action(
    db_session,
    action_type,
    evidence_summary,
    expected_command_type,
    result_field,
    expected_value,
) -> None:
    user, service = create_service_context(
        db_session,
    )

    _incident, recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v2.0.0",
        )
    )

    recommendation.action_type = action_type
    recommendation.evidence_summary = (
        evidence_summary
    )
    db_session.flush()

    result = execute_remediation(
        db=db_session,
        remediation_id=recommendation.id,
        now=datetime.now(timezone.utc),
    )

    assert (
        result.execution.execution_status
        == RemediationExecutionStatus.SUCCEEDED
    )
    assert (
        result.recommendation.status
        == RecommendationStatus.COMPLETED
    )
    assert (
        result.output["command_type"]
        == expected_command_type
    )
    assert result.output["status"] == "COMPLETED"
    assert (
        result.output[result_field]
        == expected_value
    )
    assert result.execution.started_at is not None
    assert result.execution.completed_at is not None
    assert (
        result.execution.command_payload[
            "simulated"
        ]
        is True
    )
    assert (
        result.execution.result_summary
        == result.output
    )


def test_rollback_emits_started_and_completed_events(
    db_session,
) -> None:
    user, service = create_service_context(
        db_session,
    )

    _incident, recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v2.0.0",
        )
    )

    result = execute_remediation(
        db=db_session,
        remediation_id=recommendation.id,
    )

    events = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.correlation_id
            == str(recommendation.incident_id),
        )
        .order_by(OutboxEvent.created_at.asc())
        .all()
    )

    assert len(events) == 2

    started_event = events[0]
    completed_event = events[1]

    assert (
        started_event.event_type
        == ROLLBACK_STARTED
    )
    assert (
        started_event.topic
        == TOPIC_REMEDIATION_COMMANDS
    )
    assert started_event.status == "PENDING"
    assert (
        started_event.payload["command_type"]
        == "ARGOCD_ROLLBACK"
    )
    assert (
        started_event.payload["execution_id"]
        == str(result.execution.id)
    )

    assert (
        completed_event.event_type
        == ROLLBACK_COMPLETED
    )
    assert (
        completed_event.topic
        == TOPIC_REMEDIATION_RESULTS
    )
    assert completed_event.status == "PENDING"
    assert (
        completed_event.payload["result"]["status"]
        == "COMPLETED"
    )
    assert (
        completed_event.payload["result"][
            "message"
        ]
        == "Rollback command accepted."
    )


def test_non_rollback_emits_generic_execution_events(
    db_session,
) -> None:
    user, service = create_service_context(
        db_session,
    )

    _incident, recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v2.0.0",
        )
    )

    recommendation.action_type = (
        ActionType.RESTART_POD
    )
    recommendation.evidence_summary = {
        "pod_name": "payment-api-7d9f",
    }
    db_session.flush()

    execute_remediation(
        db=db_session,
        remediation_id=recommendation.id,
    )

    events = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.correlation_id
            == str(recommendation.incident_id),
        )
        .order_by(OutboxEvent.created_at.asc())
        .all()
    )

    assert [
        event.event_type
        for event in events
    ] == [
        REMEDIATION_COMMAND_CREATED,
        REMEDIATION_COMPLETED,
    ]


def test_duplicate_execution_is_blocked(
    db_session,
) -> None:
    user, service = create_service_context(
        db_session,
    )

    _incident, recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v2.0.0",
        )
    )

    execute_remediation(
        db=db_session,
        remediation_id=recommendation.id,
    )

    with pytest.raises(
        DuplicateRemediationExecutionError,
    ):
        execute_remediation(
            db=db_session,
            remediation_id=recommendation.id,
        )
