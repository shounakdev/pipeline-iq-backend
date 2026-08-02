from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4


import pytest

from app.models import ActionType
from app.remediation.recommendation_service import (
    evaluate_remediation_recommendation,
)

from unittest.mock import MagicMock

from app.remediation import (
    recommendation_service as service_module,
)

def make_incident():
    return SimpleNamespace(
        id=uuid4(),
        failure_started_at=datetime(
            2026,
            8,
            1,
            10,
            30,
            tzinfo=timezone.utc,
        ),
        detected_at=datetime(
            2026,
            8,
            1,
            10,
            35,
            tzinfo=timezone.utc,
        ),
    )


def make_deployment(
    *,
    rollout_status: str = "HEALTHY",
    previous_revision: str | None = "revision-previous",
):
    return SimpleNamespace(
        id=uuid4(),
        kubernetes_rollout_status=rollout_status,
        previous_revision=previous_revision,
        deployed_at=datetime(
            2026,
            8,
            1,
            10,
            20,
            tzinfo=timezone.utc,
        ),
    )


def make_report(
    category: str = "UNKNOWN",
    confidence: str = "MEDIUM",
    probable_root_cause: str | None = None,
):
    return SimpleNamespace(
        confidence=confidence,
        report_json={
            "root_cause_category": category,
            "confidence": confidence,
            "probable_root_cause": (
                probable_root_cause
            ),
        },
    )


def make_health(
    *,
    cpu_usage: float | None = None,
    memory_usage: float | None = None,
    replica_count: int | None = None,
    available_replicas: int | None = None,
):
    return SimpleNamespace(
        cpu_usage=cpu_usage,
        memory_usage=memory_usage,
        replica_count=replica_count,
        available_replicas=available_replicas,
    )


def fact(fact_type: str) -> dict:
    return {
        "fact_type": fact_type,
        "polarity": "SUPPORTING",
        "evidence_paths": [],
    }


def test_recommends_redeploy_for_failed_rollout():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "deployment": {
                "deployment_status": "FAILED",
            },
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 1,
            },
        },
        report=make_report(
            "APPLICATION_REGRESSION",
        ),
        deployment=make_deployment(
            rollout_status="FAILED",
        ),
    )

    assert decision is not None
    assert (
        decision.action_type
        == ActionType.REDEPLOY_REVISION
    )
    assert (
        decision.rule_code
        == "FAILED_OR_INCOMPLETE_ROLLOUT"
    )
    assert (
        decision.evidence_summary["rule_code"]
        == decision.rule_code
    )


def test_redeploy_has_priority_over_rollback():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "deployment": {
                "deployment_status": "FAILED",
                "minutes_before_failure": 5,
            },
            "metrics": {
                "error_rate_before": 0.01,
                "error_rate_after": 0.20,
            },
            "derived_facts": [
                fact(
                    "DEPLOYMENT_TEMPORAL_CORRELATION"
                ),
                fact(
                    "ERROR_RATE_INCREASED_AFTER_DEPLOYMENT"
                ),
            ],
        },
        report=make_report(
            "APPLICATION_REGRESSION",
        ),
        deployment=make_deployment(
            rollout_status="FAILED",
        ),
    )

    assert decision is not None
    assert (
        decision.action_type
        == ActionType.REDEPLOY_REVISION
    )


def test_recommends_redeploy_for_incomplete_rollout():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "kubernetes": {
                "desired_replicas": 4,
                "available_replicas": 2,
                "rollout_completed": False,
            },
        },
    )

    assert decision is not None
    assert (
        decision.action_type
        == ActionType.REDEPLOY_REVISION
    )


def test_does_not_redeploy_only_because_service_is_unhealthy():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "kubernetes": {
                "status": "UNHEALTHY",
                "desired_replicas": 3,
                "available_replicas": 1,
            },
        },
    )

    assert decision.action_type is None


def test_recommends_rollback_for_linked_regression():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "deployment": {
                "status": "COLLECTED",
                "minutes_before_failure": 5,
            },
            "metrics": {
                "error_rate_before": 0.01,
                "error_rate_after": 0.18,
            },
            "derived_facts": [
                fact(
                    "DEPLOYMENT_TEMPORAL_CORRELATION"
                ),
            ],
        },
        report=make_report(
            "APPLICATION_REGRESSION",
        ),
        deployment=make_deployment(),
    )

    assert decision is not None
    assert (
        decision.action_type
        == ActionType.ROLLBACK_DEPLOYMENT
    )
    assert (
        decision.rule_code
        == "RECENT_DEPLOYMENT_REGRESSION"
    )
    assert (
        decision.evidence_summary["rule_code"]
        == decision.rule_code
    )
    assert (
        decision.evidence_summary[
            "previous_revision"
        ]
        == "revision-previous"
    )


def test_does_not_rollback_without_previous_revision():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "deployment": {
                "minutes_before_failure": 5,
            },
            "metrics": {
                "error_rate_before": 0.01,
                "error_rate_after": 0.18,
            },
            "derived_facts": [
                fact(
                    "DEPLOYMENT_TEMPORAL_CORRELATION"
                ),
            ],
        },
        report=make_report(
            "APPLICATION_REGRESSION",
        ),
        deployment=make_deployment(
            previous_revision=None,
        ),
    )

    assert decision.action_type is None


def test_does_not_rollback_outside_correlation_window():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "deployment": {
                "minutes_before_failure": 90,
            },
            "metrics": {
                "error_rate_before": 0.01,
                "error_rate_after": 0.18,
            },
            "derived_facts": [
                fact(
                    "DEPLOYMENT_TEMPORAL_CORRELATION"
                ),
            ],
        },
        report=make_report(
            "APPLICATION_REGRESSION",
        ),
        deployment=make_deployment(),
        correlation_window_minutes=60,
    )

    assert decision.action_type is None


def test_does_not_search_arbitrary_rca_prose():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "deployment": {
                "minutes_before_failure": 5,
            },
            "metrics": {
                "error_rate_before": 0.01,
                "error_rate_after": 0.18,
            },
            "derived_facts": [
                fact(
                    "DEPLOYMENT_TEMPORAL_CORRELATION"
                ),
            ],
        },
        report=make_report(
            category="UNKNOWN",
            probable_root_cause=(
                "A deployment might have caused this."
            ),
        ),
        deployment=make_deployment(),
    )

    assert decision.action_type is None


def test_recommends_restart_for_exactly_one_bad_pod():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 2,
                "pod_statuses": [
                    {
                        "name": "payment-api-1",
                        "state": "Ready",
                    },
                    {
                        "name": "payment-api-2",
                        "state": "CrashLoopBackOff",
                    },
                    {
                        "name": "payment-api-3",
                        "state": "Ready",
                    },
                ],
            },
        },
        report=make_report("UNKNOWN"),
    )

    assert decision is not None
    assert (
        decision.action_type
        == ActionType.RESTART_POD
    )
    assert (
        decision.rule_code
        == "SINGLE_UNHEALTHY_POD"
    )
    assert (
        decision.evidence_summary["rule_code"]
        == decision.rule_code
    )
    assert (
        decision.evidence_summary["pod_name"]
        == "payment-api-2"
    )


def test_does_not_restart_when_multiple_pods_are_unhealthy():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 1,
                "pod_statuses": [
                    {
                        "name": "payment-api-1",
                        "state": "CrashLoopBackOff",
                    },
                    {
                        "name": "payment-api-2",
                        "state": "NotReady",
                    },
                    {
                        "name": "payment-api-3",
                        "state": "Ready",
                    },
                ],
            },
        },
        report=make_report("UNKNOWN"),
    )

    assert decision.action_type is None


def test_does_not_restart_when_all_replicas_are_unavailable():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 0,
                "pod_statuses": [
                    {
                        "name": "payment-api-1",
                        "state": "CrashLoopBackOff",
                    },
                ],
            },
        },
        report=make_report("UNKNOWN"),
    )

    assert decision.action_type is None


def test_does_not_restart_for_application_wide_regression():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 2,
                "pod_statuses": [
                    {
                        "name": "payment-api-1",
                        "state": "CrashLoopBackOff",
                    },
                ],
            },
        },
        report=make_report(
            "APPLICATION_REGRESSION",
        ),
    )

    assert decision.action_type is None


def test_recommends_scale_for_verified_saturation():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "metrics": {
                "cpu_saturated": True,
                "cpu_saturation_sustained": True,
                "request_load_elevated": True,
                "request_rate_before": 100,
                "request_rate_after": 180,
            },
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 3,
                "maximum_replicas": 6,
            },
        },
        report=make_report("UNKNOWN"),
    )

    assert decision is not None
    assert (
        decision.action_type
        == ActionType.SCALE_REPLICAS
    )
    assert (
        decision.rule_code
        == "VERIFIED_LOAD_SATURATION"
    )
    assert (
        decision.evidence_summary["rule_code"]
        == decision.rule_code
    )


def test_recommends_scale_from_sustained_health_samples():
    health_history = [
        make_health(cpu_usage=91),
        make_health(cpu_usage=89),
        make_health(cpu_usage=88),
    ]

    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "metrics": {
                "request_load_elevated": True,
            },
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 3,
                "maximum_replica_limit_not_reached": True,
            },
        },
        report=make_report("UNKNOWN"),
        health_history=health_history,
    )

    assert decision is not None
    assert (
        decision.action_type
        == ActionType.SCALE_REPLICAS
    )


def test_does_not_scale_for_one_high_cpu_sample():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "metrics": {
                "cpu_saturated": True,
                "request_load_elevated": True,
            },
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 3,
                "maximum_replicas": 6,
            },
        },
        report=make_report("UNKNOWN"),
        health_history=[
            make_health(cpu_usage=95),
        ],
    )

    assert decision.action_type is None


def test_does_not_scale_without_elevated_request_load():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "metrics": {
                "cpu_saturated": True,
                "cpu_saturation_sustained": True,
                "request_load_elevated": False,
            },
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 3,
                "maximum_replicas": 6,
            },
        },
        report=make_report("UNKNOWN"),
    )

    assert decision.action_type is None


def test_does_not_scale_when_replica_limit_is_reached():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "metrics": {
                "memory_saturated": True,
                "memory_saturation_sustained": True,
                "request_load_elevated": True,
            },
            "kubernetes": {
                "desired_replicas": 6,
                "available_replicas": 6,
                "maximum_replicas": 6,
            },
        },
        report=make_report("UNKNOWN"),
    )

    assert decision.action_type is None


def test_restart_has_priority_over_scale():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "metrics": {
                "cpu_saturated": True,
                "cpu_saturation_sustained": True,
                "request_load_elevated": True,
            },
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 3,
                "maximum_replicas": 6,
                "pod_statuses": [
                    {
                        "name": "payment-api-2",
                        "state": "NotReady",
                    },
                ],
            },
        },
        report=make_report("UNKNOWN"),
    )

    assert decision is not None
    assert (
        decision.action_type
        == ActionType.RESTART_POD
    )


def test_returns_none_for_insufficient_evidence():
    decision = evaluate_remediation_recommendation(
        incident=make_incident(),
        evidence_payload={
            "deployment": {
                "status": "NO_DATA",
            },
            "metrics": {
                "status": "PARTIAL",
            },
            "kubernetes": {
                "status": "NO_DATA",
            },
        },
        report=make_report(
            "INSUFFICIENT_EVIDENCE",
            confidence="LOW",
        ),
    )

    assert decision.action_type is None


def test_rejects_invalid_correlation_window():
    with pytest.raises(
        ValueError,
        match="Correlation window",
    ):
        evaluate_remediation_recommendation(
            incident=make_incident(),
            evidence_payload={},
            correlation_window_minutes=0,
        )

def make_service_inputs():
    incident_id = uuid4()
    evidence_id = uuid4()
    report_id = uuid4()

    incident = SimpleNamespace(
        id=incident_id,
        primary_service_id="payment-service-id",
        environment="production",
        suspected_deployment_id=None,
        failure_started_at=datetime(
            2026,
            8,
            1,
            10,
            30,
            tzinfo=timezone.utc,
        ),
        detected_at=datetime(
            2026,
            8,
            1,
            10,
            35,
            tzinfo=timezone.utc,
        ),
    )

    evidence = SimpleNamespace(
        id=evidence_id,
        incident_id=incident_id,
        status="COMPLETED",
        evidence_payload={
            "deployment": {
                "deployment_status": "FAILED",
            },
            "kubernetes": {
                "desired_replicas": 3,
                "available_replicas": 1,
            },
        },
    )

    report = SimpleNamespace(
        id=report_id,
        incident_id=incident_id,
        status="COMPLETED",
        confidence="HIGH",
        report_json={
            "root_cause_category": (
                "DEPLOYMENT_CHANGE"
            ),
            "confidence": "HIGH",
        },
    )

    return incident, evidence, report


def configure_service_repositories(
    monkeypatch,
    *,
    incident,
    evidence,
    report,
    active_recommendation=None,
    latest_recommendation=None,
):
    monkeypatch.setattr(
        service_module.repository,
        "get_incident_by_id",
        lambda *_args, **_kwargs: incident,
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_latest_incident_evidence",
        lambda *_args, **_kwargs: evidence,
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_latest_rca_report",
        lambda *_args, **_kwargs: report,
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_latest_service_health",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_service_health_history",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_active_recommendation",
        lambda *_args, **_kwargs: (
            active_recommendation
        ),
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_latest_recommendation",
        lambda *_args, **_kwargs: (
            latest_recommendation
        ),
    )


def test_active_recommendation_is_returned_without_duplicate(
    monkeypatch: pytest.MonkeyPatch,
):
    incident, evidence, report = (
        make_service_inputs()
    )
    existing = SimpleNamespace(
        id=uuid4(),
        incident_id=incident.id,
        action_type=ActionType.REDEPLOY_REVISION,
        status="PENDING_APPROVAL",
        evidence_summary={
            "incident_evidence_id": str(
                evidence.id,
            ),
            "rca_report_id": str(report.id),
        },
    )

    configure_service_repositories(
        monkeypatch,
        incident=incident,
        evidence=evidence,
        report=report,
        active_recommendation=existing,
    )

    create_mock = MagicMock()
    audit_mock = MagicMock()
    event_mock = MagicMock()

    monkeypatch.setattr(
        service_module.repository,
        "create_recommendation",
        create_mock,
    )
    monkeypatch.setattr(
        service_module.repository,
        "create_recommendation_audit_event",
        audit_mock,
    )
    monkeypatch.setattr(
        service_module,
        "create_remediation_recommended_event",
        event_mock,
    )

    db = MagicMock()

    result = service_module.recommend_remediation(
        db=db,
        incident_id=incident.id,
        created_by="operator-id",
    )

    assert result.created is False
    assert result.recommendation is existing

    create_mock.assert_not_called()
    audit_mock.assert_not_called()
    event_mock.assert_not_called()
    db.commit.assert_not_called()


def test_terminal_recommendation_requires_newer_inputs(
    monkeypatch: pytest.MonkeyPatch,
):
    incident, evidence, report = (
        make_service_inputs()
    )
    terminal_recommendation = SimpleNamespace(
        id=uuid4(),
        incident_id=incident.id,
        action_type=ActionType.REDEPLOY_REVISION,
        status="REJECTED",
        evidence_summary={
            "incident_evidence_id": str(
                evidence.id,
            ),
            "rca_report_id": str(report.id),
        },
    )

    configure_service_repositories(
        monkeypatch,
        incident=incident,
        evidence=evidence,
        report=report,
        active_recommendation=None,
        latest_recommendation=(
            terminal_recommendation
        ),
    )

    create_mock = MagicMock()
    event_mock = MagicMock()

    monkeypatch.setattr(
        service_module.repository,
        "create_recommendation",
        create_mock,
    )
    monkeypatch.setattr(
        service_module,
        "create_remediation_recommended_event",
        event_mock,
    )

    with pytest.raises(
        service_module.RecommendationInputsNotChangedError,
    ):
        service_module.recommend_remediation(
            db=MagicMock(),
            incident_id=incident.id,
            created_by="operator-id",
        )

    create_mock.assert_not_called()
    event_mock.assert_not_called()


def test_newer_inputs_create_recommendation_audit_and_event(
    monkeypatch: pytest.MonkeyPatch,
):
    incident, evidence, report = (
        make_service_inputs()
    )
    older_recommendation = SimpleNamespace(
        id=uuid4(),
        incident_id=incident.id,
        status="REJECTED",
        evidence_summary={
            "incident_evidence_id": str(
                uuid4(),
            ),
            "rca_report_id": str(uuid4()),
        },
    )

    configure_service_repositories(
        monkeypatch,
        incident=incident,
        evidence=evidence,
        report=report,
        active_recommendation=None,
        latest_recommendation=(
            older_recommendation
        ),
    )

    captured = {}

    def fake_create_recommendation(
        _db,
        recommendation_data,
    ):
        captured["data"] = recommendation_data

        return SimpleNamespace(
            id=uuid4(),
            incident_id=(
                recommendation_data.incident_id
            ),
            service_id=(
                recommendation_data.service_id
            ),
            environment=(
                recommendation_data.environment
            ),
            action_type=(
                recommendation_data.action_type
            ),
            reason=recommendation_data.reason,
            evidence_summary=(
                recommendation_data.evidence_summary
            ),
            confidence=(
                recommendation_data.confidence
            ),
            status="PENDING_APPROVAL",
            created_by=(
                recommendation_data.created_by
            ),
            created_at=datetime.now(
                timezone.utc,
            ),
        )

    monkeypatch.setattr(
        service_module.repository,
        "create_recommendation",
        fake_create_recommendation,
    )

    audit_mock = MagicMock()
    event_mock = MagicMock()

    monkeypatch.setattr(
        service_module.repository,
        "create_recommendation_audit_event",
        audit_mock,
    )
    monkeypatch.setattr(
        service_module,
        "create_remediation_recommended_event",
        event_mock,
    )

    db = MagicMock()

    result = service_module.recommend_remediation(
        db=db,
        incident_id=incident.id,
        created_by="operator-id",
    )

    assert result.created is True

    stored_summary = (
        captured["data"].evidence_summary
    )

    assert stored_summary["incident_id"] == str(
        incident.id
    )
    assert (
        stored_summary["incident_evidence_id"]
        == str(evidence.id)
    )
    assert stored_summary["rca_report_id"] == str(
        report.id
    )
    assert (
        stored_summary["rule_code"]
        == "FAILED_OR_INCOMPLETE_ROLLOUT"
    )

    audit_mock.assert_called_once()
    event_mock.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(
        result.recommendation
    )


def test_missing_evidence_stops_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
):
    incident, _, report = make_service_inputs()

    monkeypatch.setattr(
        service_module.repository,
        "get_incident_by_id",
        lambda *_args, **_kwargs: incident,
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_latest_incident_evidence",
        lambda *_args, **_kwargs: None,
    )

    event_mock = MagicMock()

    monkeypatch.setattr(
        service_module,
        "create_remediation_recommended_event",
        event_mock,
    )

    with pytest.raises(
        service_module.IncidentEvidenceMissingError,
    ):
        service_module.recommend_remediation(
            db=MagicMock(),
            incident_id=incident.id,
        )

    event_mock.assert_not_called()


def test_missing_rca_stops_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
):
    incident, evidence, _ = make_service_inputs()

    monkeypatch.setattr(
        service_module.repository,
        "get_incident_by_id",
        lambda *_args, **_kwargs: incident,
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_latest_incident_evidence",
        lambda *_args, **_kwargs: evidence,
    )
    monkeypatch.setattr(
        service_module.repository,
        "get_latest_rca_report",
        lambda *_args, **_kwargs: None,
    )

    event_mock = MagicMock()

    monkeypatch.setattr(
        service_module,
        "create_remediation_recommended_event",
        event_mock,
    )

    with pytest.raises(
        service_module.RCAReportMissingError,
    ):
        service_module.recommend_remediation(
            db=MagicMock(),
            incident_id=incident.id,
        )

    event_mock.assert_not_called()