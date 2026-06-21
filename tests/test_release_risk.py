from types import SimpleNamespace


try:
    from app.pipelineiq.risk.release_risk import calculate_risk_score
except ImportError:
    from app.pipelineiq.risk.release_risk import calculate_release_risk as calculate_risk_score


def normalize_result(result):
    if isinstance(result, tuple):
        return result

    if isinstance(result, dict):
        return (
            result.get("risk_score"),
            result.get("risk_level"),
            result.get("risk_summary"),
            result.get("recommendations"),
        )

    raise AssertionError(f"Unexpected risk result type: {type(result)}")


def fake_run(**overrides):
    defaults = {
        "build_status": "SUCCESS",
        "test_status": "SUCCESS",
        "quality_gate": "OK",
        "trivy_critical": 0,
        "trivy_high": 0,
        "trivy_medium": 0,
        "trivy_low": 0,
        "coverage": 85,
        "bugs": 0,
        "vulnerabilities": 0,
        "code_smells": 0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_risk_score_low():
    run = fake_run(
        build_status="SUCCESS",
        test_status="SUCCESS",
        quality_gate="OK",
        trivy_critical=0,
        trivy_high=0,
        coverage=85,
    )

    score, level, summary, recommendations = normalize_result(calculate_risk_score(run))

    assert level == "LOW"
    assert score < 25
    assert summary
    assert isinstance(recommendations, list)


def test_risk_score_critical_due_to_security():
    run = fake_run(
        build_status="SUCCESS",
        test_status="SUCCESS",
        quality_gate="OK",
        trivy_critical=4,
        trivy_high=6,
        coverage=70,
    )

    score, level, summary, recommendations = normalize_result(calculate_risk_score(run))

    assert level in ["HIGH", "CRITICAL"]
    assert score >= 50
    assert summary
    assert isinstance(recommendations, list)


def test_risk_score_increases_when_build_fails():
    healthy_run = fake_run(build_status="SUCCESS", test_status="SUCCESS")
    failed_run = fake_run(build_status="FAILED", test_status="SUCCESS")

    healthy_score, *_ = normalize_result(calculate_risk_score(healthy_run))
    failed_score, failed_level, *_ = normalize_result(calculate_risk_score(failed_run))

    assert failed_score > healthy_score
    assert failed_level in ["MEDIUM", "HIGH", "CRITICAL"]


def test_risk_score_increases_when_tests_fail():
    healthy_run = fake_run(build_status="SUCCESS", test_status="SUCCESS")
    failed_run = fake_run(build_status="SUCCESS", test_status="FAILED")

    healthy_score, *_ = normalize_result(calculate_risk_score(healthy_run))
    failed_score, failed_level, *_ = normalize_result(calculate_risk_score(failed_run))

    assert failed_score > healthy_score
    assert failed_level in ["MEDIUM", "HIGH", "CRITICAL"]
