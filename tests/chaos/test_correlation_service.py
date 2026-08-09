from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.chaos import repository
from app.chaos.services.correlation_service import correlate_event
from app.chaos.services.benchmark_service import calculate_benchmark
from app.chaos.services.observation_service import as_utc
from app.events.constants import (
    ALERT_CREATED,
    INCIDENT_CREATED,
    RCA_COMPLETED,
    RECOVERY_VERIFIED,
    SERVICE_DOWN,
    REMEDIATION_APPROVED,
    REMEDIATION_COMPLETED,
    REMEDIATION_RECOMMENDED,
)
from app.models import (
    ActionType,
    ApprovalDecision,
    BenchmarkStatus,
    ChaosObservationType,
    ChaosRunStatus,
    ChaosScenarioType,
    EventRecord,
    OutboxEvent,
    Incident,
    IncidentEvidence,
    IncidentSeverity,
    IncidentStatus,
    ExperimentBenchmark,
    Project,
    RCAConfidence,
    RCAReport,
    RCAReportStatus,
    RecoveryVerification,
    RecoveryVerificationStatus,
    ReliabilityAlert,
    RemediationApproval,
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationRecommendation,
    Service,
    User,
)
from app.database import Base


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


@pytest.fixture
def correlation_db():
    engine = create_engine("sqlite:///:memory:")
    report_json_default = RCAReport.__table__.c.report_json.server_default
    RCAReport.__table__.c.report_json.server_default = None
    tables = [
        User.__table__,
        Project.__table__,
        Service.__table__,
        ReliabilityAlert.__table__,
        Incident.__table__,
        IncidentEvidence.__table__,
        RCAReport.__table__,
        RemediationRecommendation.__table__,
        RemediationApproval.__table__,
        RemediationExecution.__table__,
        RecoveryVerification.__table__,
        repository.ChaosExperiment.__table__,
        repository.ChaosRun.__table__,
        repository.ChaosObservation.__table__,
        ExperimentBenchmark.__table__,
        OutboxEvent.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine, tables=reversed(tables))
        RCAReport.__table__.c.report_json.server_default = report_json_default
        engine.dispose()


def _event(event_type, occurred_at, **payload):
    return EventRecord(
        event_id=f"evt-{uuid4()}",
        event_type=event_type,
        topic="test.events",
        correlation_id=str(uuid4()),
        service_id=payload.get("service_id"),
        environment=payload.get("environment"),
        timestamp=occurred_at,
        payload={"occurred_at": occurred_at.isoformat(), **payload},
        raw_event={},
    )


def _context(correlation_db, *, service_name="checkout"):
    now = datetime.now(timezone.utc)
    user = User(
        id=str(uuid4()),
        email=f"chaos-10f-{uuid4()}@example.com",
        password_hash="unused",
        full_name="Chaos Operator",
        is_active=True,
    )
    project = Project(
        id=str(uuid4()),
        name=f"Chaos 10F {uuid4()}",
        created_by=user.id,
    )
    service = Service(
        id=str(uuid4()),
        project_id=project.id,
        name=f"{service_name}-{uuid4()}",
        service_type="BACKEND",
    )
    correlation_db.add_all([user, project, service])
    correlation_db.flush()
    experiment = repository.create_experiment(
        correlation_db,
        name="10F correlation",
        scenario_type=ChaosScenarioType.POD_KILL,
        target_service_id=service.id,
        target_environment="staging",
        target_namespace="platformiq-staging",
        failure_type="POD_KILL",
        failure_config={},
        expected_behavior={},
        created_by=user.id,
    )
    run = repository.create_run(
        correlation_db,
        experiment_id=experiment.id,
        status=ChaosRunStatus.OBSERVING,
        started_at=now - timedelta(seconds=5),
        duration_seconds=1800,
        deadline_at=now + timedelta(minutes=30),
    )
    repository.update_run(
        correlation_db,
        chaos_run=run,
        failure_injected_at=now,
    )
    return service, run, now


def _incident(correlation_db, service, detected_at):
    incident = Incident(
        id=uuid4(),
        incident_number=f"INC-10F-{uuid4().hex[:8]}",
        title="Chaos-correlated failure",
        severity=IncidentSeverity.SEV_2,
        status=IncidentStatus.DETECTED,
        primary_service_id=service.id,
        environment="staging",
        detected_at=detected_at,
    )
    correlation_db.add(incident)
    correlation_db.flush()
    return incident


def _link_incident(correlation_db, service, run, when):
    incident = _incident(correlation_db, service, when)
    correlate_event(
        correlation_db,
        _event(
            INCIDENT_CREATED,
            when,
            incident_id=str(incident.id),
            service_id=service.id,
            environment="staging",
        ),
    )
    return incident


def test_alert_after_injection_is_linked(correlation_db):
    service, run, injected_at = _context(correlation_db)
    correlate_event(
        correlation_db,
        _event(
            ALERT_CREATED,
            injected_at + timedelta(seconds=5),
            alert_id="alert-after",
            service_id=service.id,
            environment="staging",
        ),
    )
    observations = repository.list_observations_for_run(correlation_db, run.id)
    assert [(item.observation_type, item.resource_id) for item in observations] == [
        (ChaosObservationType.ALERT_CREATED, "alert-after")
    ]

def test_legacy_observability_alert_is_linked(correlation_db):
    service, run, injected_at = _context(correlation_db)
    event = _event(
        SERVICE_DOWN,
        injected_at + timedelta(seconds=3),
        service_id=service.id,
        environment="staging",
        snapshot_id="snapshot-live",
    )

    correlate_event(correlation_db, event)

    observations = repository.list_observations_for_run(
        correlation_db,
        run.id,
    )
    assert len(observations) == 1
    assert (
        observations[0].observation_type
        == ChaosObservationType.ALERT_CREATED
    )
    assert observations[0].resource_id == event.event_id

def test_alert_before_injection_is_not_linked(correlation_db):
    service, run, injected_at = _context(correlation_db)
    result = correlate_event(
        correlation_db,
        _event(
            ALERT_CREATED,
            injected_at - timedelta(microseconds=1),
            alert_id="alert-before",
            service_id=service.id,
            environment="staging",
        ),
    )
    assert result is None
    assert repository.list_observations_for_run(correlation_db, run.id) == []


def test_earliest_matching_alert_is_retained(correlation_db):
    service, run, injected_at = _context(correlation_db)
    for seconds, alert_id in [(20, "alert-later"), (5, "alert-earlier")]:
        correlate_event(
            correlation_db,
            _event(
                ALERT_CREATED,
                injected_at + timedelta(seconds=seconds),
                alert_id=alert_id,
                service_id=service.id,
                environment="staging",
            ),
        )
    observations = repository.list_observations_for_run(correlation_db, run.id)
    assert len(observations) == 1
    assert observations[0].resource_id == "alert-earlier"
    assert as_utc(observations[0].observed_at) == (
        injected_at + timedelta(seconds=5)
    )


def test_incident_links_to_correct_run_and_ignores_other_service(correlation_db):
    service, run, injected_at = _context(correlation_db)
    other_service, other_run, _ = _context(correlation_db, service_name="orders")
    incident = _incident(
        correlation_db, service, injected_at + timedelta(seconds=10)
    )
    correlate_event(
        correlation_db,
        _event(
            INCIDENT_CREATED,
            incident.detected_at,
            incident_id=str(incident.id),
            service_id=service.id,
            environment="staging",
        ),
    )
    assert run.incident_id == incident.id
    assert other_run.incident_id is None


def test_existing_incident_link_is_not_overwritten(correlation_db):
    service, run, injected_at = _context(correlation_db)
    original = _incident(
        correlation_db, service, injected_at + timedelta(seconds=2)
    )
    repository.link_run_artifacts(
        correlation_db, chaos_run=run, incident_id=original.id
    )
    later = _incident(
        correlation_db, service, injected_at + timedelta(seconds=10)
    )
    result = correlate_event(
        correlation_db,
        _event(
            INCIDENT_CREATED,
            later.detected_at,
            incident_id=str(later.id),
            service_id=service.id,
            environment="staging",
        ),
    )
    assert result is None
    assert run.incident_id == original.id


def test_rca_report_links_through_the_incident(correlation_db):
    service, run, injected_at = _context(correlation_db)
    incident = _link_incident(
        correlation_db, service, run, injected_at + timedelta(seconds=5)
    )
    evidence = IncidentEvidence(
        incident_id=incident.id,
        version=1,
        status="COMPLETED",
        schema_version="1.0",
    )
    correlation_db.add(evidence)
    correlation_db.flush()
    completed_at = injected_at + timedelta(seconds=15)
    report = RCAReport(
        incident_id=incident.id,
        evidence_id=evidence.id,
        version=1,
        status=RCAReportStatus.COMPLETED,
        generated_at=completed_at,
        prompt_version="rca_v1",
    )
    correlation_db.add(report)
    correlation_db.flush()
    correlate_event(
        correlation_db,
        _event(RCA_COMPLETED, completed_at, rca_report_id=str(report.id)),
    )
    assert run.rca_report_id == report.id
    assert run.rca_report.evidence_id == evidence.id


def _recommendation(correlation_db, service, incident, created_at):
    recommendation = RemediationRecommendation(
        incident_id=incident.id,
        service_id=service.id,
        environment="staging",
        action_type=ActionType.RESTART_POD,
        reason="Recover from injected pod failure",
        evidence_summary={},
        confidence=RCAConfidence.HIGH,
        created_at=created_at,
    )
    correlation_db.add(recommendation)
    correlation_db.flush()
    return recommendation


def test_remediation_recommendation_links_to_run(correlation_db):
    service, run, injected_at = _context(correlation_db)
    incident = _link_incident(
        correlation_db, service, run, injected_at + timedelta(seconds=5)
    )
    created_at = injected_at + timedelta(seconds=20)
    recommendation = _recommendation(
        correlation_db, service, incident, created_at
    )
    correlate_event(
        correlation_db,
        _event(
            REMEDIATION_RECOMMENDED,
            created_at,
            recommendation_id=str(recommendation.id),
        ),
    )
    assert run.remediation_id == recommendation.id


def test_remediation_execution_links_to_run(correlation_db):
    service, run, injected_at = _context(correlation_db)
    incident = _link_incident(
        correlation_db, service, run, injected_at + timedelta(seconds=5)
    )
    recommendation = _recommendation(
        correlation_db, service, incident, injected_at + timedelta(seconds=10)
    )
    completed_at = injected_at + timedelta(seconds=30)
    execution = RemediationExecution(
        remediation_id=recommendation.id,
        command_type=ActionType.RESTART_POD,
        command_payload={},
        execution_status=RemediationExecutionStatus.SUCCEEDED,
        started_at=completed_at - timedelta(seconds=2),
        completed_at=completed_at,
        result_summary={},
        created_at=completed_at - timedelta(seconds=2),
    )
    correlation_db.add(execution)
    correlation_db.flush()
    correlate_event(
        correlation_db,
        _event(REMEDIATION_COMPLETED, completed_at, execution_id=str(execution.id)),
    )
    assert run.remediation_id == recommendation.id
    assert run.remediation_execution_id == execution.id


def test_recovery_event_completes_observation_timeline(correlation_db):
    service, run, injected_at = _context(correlation_db)
    incident = _link_incident(
        correlation_db, service, run, injected_at + timedelta(seconds=5)
    )
    recommendation = _recommendation(
        correlation_db, service, incident, injected_at + timedelta(seconds=10)
    )
    verified_at = injected_at + timedelta(seconds=40)
    execution = RemediationExecution(
        remediation_id=recommendation.id,
        command_type=ActionType.RESTART_POD,
        command_payload={},
        execution_status=RemediationExecutionStatus.SUCCEEDED,
        started_at=verified_at - timedelta(seconds=5),
        completed_at=verified_at - timedelta(seconds=2),
        result_summary={},
        created_at=verified_at - timedelta(seconds=5),
    )
    correlation_db.add(execution)
    correlation_db.flush()
    verification = RecoveryVerification(
        remediation_id=recommendation.id,
        remediation_execution_id=execution.id,
        verification_status=RecoveryVerificationStatus.VERIFIED,
        verified_at=verified_at,
        metrics_snapshot={},
    )
    correlation_db.add(verification)
    correlation_db.flush()
    correlate_event(
        correlation_db,
        _event(
            RECOVERY_VERIFIED,
            verified_at,
            verification_id=str(verification.id),
        ),
    )
    assert run.recovery_verification_id == verification.id
    assert repository.list_observations_for_run(correlation_db, run.id)[-1].observation_type == (
        ChaosObservationType.RECOVERY_COMPLETED
    )


def test_complete_experiment_chain_links_and_calculates_trustworthy_benchmark(
    correlation_db,
):
    """Sprint 10J acceptance path from injection through verified recovery."""
    service, run, injected_at = _context(correlation_db)
    run.experiment.expected_behavior = {"diagnosis": "POD_FAILURE"}
    repository.create_observation(
        correlation_db,
        chaos_run_id=run.id,
        observation_type=ChaosObservationType.FAILURE_INJECTED,
        source="chaos-adapter",
        observed_at=injected_at,
        resource_type="PodChaos",
        resource_id=f"platformiq-pod-kill-{run.id}",
        details={"status": "INJECTED"},
    )
    repository.create_observation(
        correlation_db,
        chaos_run_id=run.id,
        observation_type=ChaosObservationType.TELEMETRY_ANOMALY,
        source="platformiq",
        observed_at=injected_at + timedelta(seconds=10),
        resource_type="ServiceHealthSnapshot",
        resource_id="snapshot-1",
        details={"status": "UNHEALTHY"},
    )

    alert_at = injected_at + timedelta(seconds=20)
    correlate_event(
        correlation_db,
        _event(
            ALERT_CREATED,
            alert_at,
            alert_id="alert-10j",
            service_id=service.id,
            environment="staging",
        ),
    )
    incident = _link_incident(
        correlation_db, service, run, injected_at + timedelta(seconds=30)
    )
    evidence = IncidentEvidence(
        incident_id=incident.id,
        version=1,
        status="COMPLETED",
        schema_version="1.0",
    )
    correlation_db.add(evidence)
    correlation_db.flush()
    rca_at = injected_at + timedelta(seconds=100)
    report = RCAReport(
        incident_id=incident.id,
        evidence_id=evidence.id,
        version=1,
        status=RCAReportStatus.COMPLETED,
        generated_at=rca_at,
        prompt_version="rca_v1",
        probable_root_cause="Injected pod failure",
        report_json={"root_cause_category": "POD_FAILURE"},
    )
    correlation_db.add(report)
    correlation_db.flush()
    correlate_event(
        correlation_db,
        _event(RCA_COMPLETED, rca_at, rca_report_id=str(report.id)),
    )

    recommended_at = injected_at + timedelta(seconds=110)
    recommendation = _recommendation(
        correlation_db, service, incident, recommended_at
    )
    correlate_event(
        correlation_db,
        _event(
            REMEDIATION_RECOMMENDED,
            recommended_at,
            recommendation_id=str(recommendation.id),
        ),
    )
    approved_at = injected_at + timedelta(seconds=125)
    approval = RemediationApproval(
        remediation_id=recommendation.id,
        approved_by=None,
        decision=ApprovalDecision.APPROVED,
        approved_at=approved_at,
    )
    correlation_db.add(approval)
    correlation_db.flush()
    correlate_event(
        correlation_db,
        _event(
            REMEDIATION_APPROVED,
            approved_at,
            recommendation_id=str(recommendation.id),
            approval_id=str(approval.id),
        ),
    )

    completed_at = injected_at + timedelta(seconds=140)
    execution = RemediationExecution(
        remediation_id=recommendation.id,
        command_type=ActionType.RESTART_POD,
        command_payload={},
        execution_status=RemediationExecutionStatus.SUCCEEDED,
        started_at=completed_at - timedelta(seconds=5),
        completed_at=completed_at,
        result_summary={},
        created_at=completed_at - timedelta(seconds=5),
    )
    correlation_db.add(execution)
    correlation_db.flush()
    correlate_event(
        correlation_db,
        _event(REMEDIATION_COMPLETED, completed_at, execution_id=str(execution.id)),
    )
    recovered_at = injected_at + timedelta(seconds=150)
    verification = RecoveryVerification(
        remediation_id=recommendation.id,
        remediation_execution_id=execution.id,
        verification_status=RecoveryVerificationStatus.VERIFIED,
        verified_at=recovered_at,
        metrics_snapshot={"healthy": True},
    )
    correlation_db.add(verification)
    correlation_db.flush()
    correlate_event(
        correlation_db,
        _event(
            RECOVERY_VERIFIED,
            recovered_at,
            verification_id=str(verification.id),
        ),
    )
    correlation_db.commit()
    correlation_db.refresh(run)

    benchmark = calculate_benchmark(correlation_db, run)
    observations = repository.list_observations_for_run(correlation_db, run.id)
    observed_types = {item.observation_type for item in observations}

    assert ChaosObservationType.FAILURE_INJECTED in observed_types
    assert ChaosObservationType.TELEMETRY_ANOMALY in observed_types
    assert ChaosObservationType.ALERT_CREATED in observed_types
    assert run.incident_id == incident.id
    assert run.rca_report_id == report.id
    assert run.remediation_id == recommendation.id
    assert run.remediation_execution_id == execution.id
    assert run.recovery_verification_id == verification.id
    assert benchmark.time_to_detect_ms == 10_000
    assert benchmark.time_to_alert_ms == 20_000
    assert benchmark.time_to_incident_ms == 30_000
    assert benchmark.time_to_diagnose_ms == 70_000
    assert benchmark.time_to_approve_ms == 15_000
    assert benchmark.time_to_recover_ms == 150_000
    assert benchmark.benchmark_status == BenchmarkStatus.PASSED