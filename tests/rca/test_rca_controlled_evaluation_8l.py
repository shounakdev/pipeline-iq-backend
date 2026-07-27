import json
from pathlib import Path

import pytest

from app.rca.llm.grounding import validate_rca_grounding


FIXTURE_DIR = Path(__file__).parent / "fixtures"


CONTROLLED_SCENARIOS = [
    {
        "fixture": "database_timeout.json",
        "expected_category": "DATABASE_DEPENDENCY",
        "min_confidence": "MEDIUM",
    },
    {
        "fixture": "artificial_latency.json",
        "expected_category": "APPLICATION_REGRESSION",
        "min_confidence": "MEDIUM",
    },
    {
        "fixture": "random_http_500.json",
        "expected_category": "APPLICATION_REGRESSION",
        "min_confidence": "MEDIUM",
    },
    {
        "fixture": "pod_crash_restart.json",
        "expected_category": "KUBERNETES_RUNTIME",
        "min_confidence": "MEDIUM",
    },
    {
        "fixture": "insufficient_telemetry.json",
        "expected_category": "UNKNOWN",
        "min_confidence": "LOW",
    },
]


CONFIDENCE_ORDER = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
}


def load_fixture(name: str) -> dict:
    with open(FIXTURE_DIR / name, "r", encoding="utf-8") as file:
        return json.load(file)


@pytest.mark.parametrize("scenario", CONTROLLED_SCENARIOS)
def test_controlled_rca_scenarios_are_grounded(scenario):
    fixture = load_fixture(scenario["fixture"])

    evidence = fixture["evidence"]
    report = fixture["expected_report"]

    assert report["primary_category"] == scenario["expected_category"]

    assert (
        CONFIDENCE_ORDER[report["confidence"]]
        >= CONFIDENCE_ORDER[scenario["min_confidence"]]
    )

    grounding_result = validate_rca_grounding(report, evidence)

    assert grounding_result.is_valid is True
    assert grounding_result.unsupported_claims == []
    assert grounding_result.missing_evidence_paths == []


def test_insufficient_telemetry_returns_low_confidence():
    fixture = load_fixture("insufficient_telemetry.json")

    report = fixture["expected_report"]

    assert report["primary_category"] == "UNKNOWN"
    assert report["confidence"] == "LOW"


def test_no_high_confidence_report_with_one_source():
    fixture = load_fixture("insufficient_telemetry.json")

    evidence = fixture["evidence"]
    report = fixture["expected_report"]

    collected_sources = [
        source
        for source, value in evidence.get("sources", {}).items()
        if isinstance(value, dict) and value.get("status") == "COLLECTED"
    ]

    if len(collected_sources) <= 1:
        assert report["confidence"] != "HIGH"
