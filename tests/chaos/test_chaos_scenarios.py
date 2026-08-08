import pytest

from app.chaos.adapters.mock_adapter import MockChaosAdapter
from app.chaos.scenarios import (
    CpuPressureScenario,
    DatabaseDelayScenario,
    FaultyReleaseScenario,
    NetworkDelayScenario,
    PodKillScenario,
)
from app.models import ChaosScenarioType


NAMESPACE = "platformiq-staging"
SERVICE = "payment-service"


@pytest.mark.parametrize(
    ("scenario", "kind", "scenario_type", "diagnosis", "remediation"),
    [
        (
            FaultyReleaseScenario(NAMESPACE),
            "HTTPChaos",
            ChaosScenarioType.FAULTY_RELEASE,
            "APPLICATION_REGRESSION",
            "ROLLBACK_DEPLOYMENT",
        ),
        (
            PodKillScenario(NAMESPACE),
            "PodChaos",
            ChaosScenarioType.POD_KILL,
            "POD_FAILURE",
            "RESTART_POD",
        ),
        (
            NetworkDelayScenario(NAMESPACE),
            "NetworkChaos",
            ChaosScenarioType.NETWORK_DELAY,
            "NETWORK_LATENCY",
            None,
        ),
        (
            DatabaseDelayScenario(NAMESPACE),
            "NetworkChaos",
            ChaosScenarioType.DATABASE_DELAY,
            "DATABASE_CONNECTIVITY",
            None,
        ),
        (
            CpuPressureScenario(NAMESPACE),
            "StressChaos",
            ChaosScenarioType.CPU_PRESSURE,
            "RESOURCE_SATURATION",
            "SCALE_REPLICAS",
        ),
    ],
)
def test_scenario_manifest_expectations_and_cleanup(
    scenario,
    kind,
    scenario_type,
    diagnosis,
    remediation,
):
    manifest = scenario.build_manifest(
        run_id="run-123",
        operator_id="operator-1",
        deadline="2026-08-08T20:30:00+00:00",
    )

    assert manifest["apiVersion"] == "chaos-mesh.org/v1alpha1"
    assert manifest["kind"] == kind
    assert manifest["metadata"]["namespace"] == NAMESPACE
    assert manifest["spec"]["selector"] == {
        "namespaces": [NAMESPACE],
        "labelSelectors": {"app": SERVICE},
    }
    assert manifest["spec"]["duration"] == scenario.duration
    assert manifest["metadata"]["annotations"][
        "platformiq.io/duration-seconds"
    ] == str(scenario.duration_seconds)
    assert scenario.scenario_type == scenario_type
    assert scenario.expected_diagnosis == diagnosis
    assert scenario.expected_remediation == remediation
    assert scenario.experiment_values()["expected_behavior"] == {
        "diagnosis": diagnosis,
        "remediation": remediation,
        "recovery_expected": True,
    }

    adapter = MockChaosAdapter()
    resource = scenario.inject(
        adapter,
        run_id="run-123",
        operator_id="operator-1",
        deadline="2026-08-08T20:30:00+00:00",
    )
    assert scenario.cleanup(adapter, resource)
    assert adapter.resources == {}


def test_network_delay_uses_required_latency_jitter_and_dependency():
    manifest = NetworkDelayScenario(NAMESPACE).build_manifest(run_id="net")
    assert manifest["spec"]["delay"] == {
        "latency": "2000ms",
        "jitter": "200ms",
        "correlation": "0",
    }


def test_faulty_release_uses_reversible_known_bad_configuration():
    scenario = FaultyReleaseScenario(NAMESPACE)
    manifest = scenario.build_manifest(run_id="release")

    assert manifest["spec"]["abort"] is True
    assert manifest["spec"]["target"] == "Request"
    assert manifest["spec"]["method"] == "GET"
    assert manifest["spec"]["path"] == "/*"
    assert manifest["metadata"]["annotations"][
        "platformiq.io/fault-profile"
    ] == "known-bad-http-configuration"


def test_pod_kill_targets_exactly_one_pod():
    manifest = PodKillScenario(NAMESPACE).build_manifest(run_id="pod")
    assert manifest["spec"]["action"] == "pod-kill"
    assert manifest["spec"]["mode"] == "one"
    


def test_database_delay_is_distinguishable_from_generic_network_latency():
    scenario = DatabaseDelayScenario(NAMESPACE)
    manifest = scenario.build_manifest(run_id="db")
    annotations = manifest["metadata"]["annotations"]

    assert manifest["spec"]["target"]["selector"]["labelSelectors"] == {
        "app": "postgres"
    }
    assert annotations["platformiq.io/dependency-type"] == "database"
    assert annotations["platformiq.io/database-port"] == "5432"
    assert "database timeout" in scenario.failure_config()[
        "evidence_signatures"
    ]


def test_cpu_pressure_defaults_match_scenario_contract():
    scenario = CpuPressureScenario(NAMESPACE)
    manifest = scenario.build_manifest(run_id="cpu")

    assert manifest["spec"]["duration"] == "180s"
    assert manifest["spec"]["stressors"]["cpu"] == {
        "workers": 2,
        "load": 90,
    }


@pytest.mark.parametrize(
    "scenario_type",
    [
        FaultyReleaseScenario,
        PodKillScenario,
        NetworkDelayScenario,
        DatabaseDelayScenario,
        CpuPressureScenario,
    ],
)
def test_duration_must_be_positive(scenario_type):
    with pytest.raises(ValueError, match="greater than zero"):
        scenario_type(NAMESPACE, duration_seconds=0)