from datetime import datetime, timedelta, timezone

from app.events.constants import (
    RECOVERY_FAILED,
    RECOVERY_VERIFIED,
    TOPIC_REMEDIATION_RESULTS,
)
from app.incidents.enums import IncidentStatus
from app.models import (
    OutboxEvent,
    RecommendationStatus,
    RecoveryVerification,
    RecoveryVerificationStatus,
    ServiceHealthSnapshot,
    ServiceHealthStatus,
)
from app.remediation.services.verification_service import (
    verify_remediation_recovery,
)
from tests.remediation.test_safety_service import (
    create_decided_recommendation,
    create_execution,
    create_service_context,
)


def prepare_verification_case(
    db_session,
    *,
    healthy: bool,
):
    user, service = create_service_context(
        db_session,
    )

    incident, recommendation = (
        create_decided_recommendation(
            db_session,
            user=user,
            service=service,
            deployment_revision="v2.0.0",
            incident_status=(
                IncidentStatus.REMEDIATING
            ),
        )
    )

    execution_time = (
        datetime.now(timezone.utc)
        - timedelta(minutes=1)
    )

    execution = create_execution(
        db_session,
        recommendation=recommendation,
        created_at=execution_time,
    )

    recommendation.status = (
        RecommendationStatus.COMPLETED
    )

    health = ServiceHealthSnapshot(
        service_id=service.id,
        service_name=service.name,
        environment="staging",
        status=(
            ServiceHealthStatus.HEALTHY
            if healthy
            else ServiceHealthStatus.DEGRADED
        ),
        latency_ms=180.0 if healthy else 1800.0,
        error_rate=0.2 if healthy else 8.5,
        cpu_usage=35.0 if healthy else 92.0,
        memory_usage=40.0 if healthy else 88.0,
        pod_restart_count=0 if healthy else 4,
        replica_count=3,
        available_replicas=3 if healthy else 1,
        source="test",
        created_at=(
            execution_time
            + timedelta(seconds=30)
        ),
    )

    db_session.add(health)
    db_session.flush()

    verification_time = (
        execution_time
        + timedelta(minutes=1)
    )

    return (
        incident,
        recommendation,
        execution,
        verification_time,
    )


def test_recovery_verification_success(
    db_session,
) -> None:
    (
        _incident,
        recommendation,
        execution,
        verification_time,
    ) = prepare_verification_case(
        db_session,
        healthy=True,
    )

    result = verify_remediation_recovery(
        db=db_session,
        remediation_id=recommendation.id,
        now=verification_time,
    )

    assert result.recovered is True
    assert (
        result.verification.verification_status
        == RecoveryVerificationStatus.VERIFIED
    )
    assert (
        result.verification.remediation_execution_id
        == execution.id
    )
    assert (
        result.verification.error_rate_recovered
        is True
    )
    assert (
        result.verification.latency_recovered
        is True
    )
    assert result.verification.pods_healthy is True
    assert (
        result.verification.restart_loop_absent
        is True
    )
    assert (
        result.verification.availability_restored
        is True
    )

    stored_verification = (
        db_session.query(RecoveryVerification)
        .filter(
            RecoveryVerification
            .remediation_execution_id
            == execution.id
        )
        .one()
    )

    assert (
        stored_verification.id
        == result.verification.id
    )


def test_failed_recovery(
    db_session,
) -> None:
    (
        _incident,
        recommendation,
        _execution,
        verification_time,
    ) = prepare_verification_case(
        db_session,
        healthy=False,
    )

    result = verify_remediation_recovery(
        db=db_session,
        remediation_id=recommendation.id,
        now=verification_time,
    )

    assert result.recovered is False
    assert (
        result.verification.verification_status
        == RecoveryVerificationStatus.FAILED
    )
    assert (
        result.verification.error_rate_recovered
        is False
    )
    assert (
        result.verification.latency_recovered
        is False
    )
    assert result.verification.pods_healthy is False
    assert (
        result.verification.restart_loop_absent
        is False
    )
    assert (
        result.verification.availability_restored
        is False
    )
    assert (
        result.recommendation.status
        == RecommendationStatus.RECOVERY_FAILED
    )


def test_incident_marked_resolved_after_successful_recovery(
    db_session,
) -> None:
    (
        incident,
        recommendation,
        _execution,
        verification_time,
    ) = prepare_verification_case(
        db_session,
        healthy=True,
    )

    verify_remediation_recovery(
        db=db_session,
        remediation_id=recommendation.id,
        now=verification_time,
    )

    db_session.refresh(incident)

    assert incident.status == IncidentStatus.RESOLVED
    assert incident.resolved_at is not None
    assert (
        recommendation.status
        == RecommendationStatus.RECOVERY_VERIFIED
    )

    event = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type
            == RECOVERY_VERIFIED,
            OutboxEvent.correlation_id
            == str(incident.id),
        )
        .one()
    )

    assert event.topic == TOPIC_REMEDIATION_RESULTS
    assert event.status == "PENDING"
    assert (
        event.payload["verification_status"]
        == "VERIFIED"
    )
    assert (
        event.payload["availability_restored"]
        is True
    )


def test_incident_marked_failed_recovery(
    db_session,
) -> None:
    (
        incident,
        recommendation,
        _execution,
        verification_time,
    ) = prepare_verification_case(
        db_session,
        healthy=False,
    )

    verify_remediation_recovery(
        db=db_session,
        remediation_id=recommendation.id,
        now=verification_time,
    )

    db_session.refresh(incident)

    assert (
        incident.status
        == IncidentStatus.FAILED_RECOVERY
    )
    assert incident.resolved_at is None
    assert (
        recommendation.status
        == RecommendationStatus.RECOVERY_FAILED
    )

    event = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type
            == RECOVERY_FAILED,
            OutboxEvent.correlation_id
            == str(incident.id),
        )
        .one()
    )

    assert event.topic == TOPIC_REMEDIATION_RESULTS
    assert event.status == "PENDING"
    assert (
        event.payload["verification_status"]
        == "FAILED"
    )
    assert (
        event.payload["availability_restored"]
        is False
    )
